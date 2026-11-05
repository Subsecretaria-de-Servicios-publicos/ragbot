"""Pruebas del login con Sovra ID, sin base de datos ni red (almacén en memoria + Sovra simulado).

Correr desde backend/:  ./venv/bin/python -m unittest discover -s tests -v
"""
import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

# Settings exige estas variables al importarse; los valores no se usan.
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://u:p@localhost/db")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx  # noqa: E402

from app.services.sovra_client import SovraClient, SovraError  # noqa: E402
from app.services.sovra_login import (  # noqa: E402
    LoginRecord, PollResult, SovraLoginService, UserRef, build_login_dcql, extract_presented,
    hash_poll_secret, issuer_matches, normalize_dni,
)

ISSUER_DID = "did:sovra:0xabc"
ISSUER_URL = f"https://api.example.com/{ISSUER_DID}"
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def cfg(**over):
    base = dict(SOVRA_LOGIN_CLAIM="dni", SOVRA_LOGIN_VCT="EmpleadoPublico",
                SOVRA_LOGIN_ISSUER_DID="", SOVRA_LOGIN_TTL_SECONDS=180)
    base.update(over)
    return SimpleNamespace(**base)


class FakeStore:
    def __init__(self, users=None):
        self.rows = {}
        self.users = users or {}  # dni -> UserRef

    async def create(self, rec):
        self.rows[rec.id] = rec

    async def get(self, login_id):
        return self.rows.get(login_id)

    async def update(self, login_id, **fields):
        for k, v in fields.items():
            setattr(self.rows[login_id], k, v)

    async def consume(self, login_id):
        rec = self.rows[login_id]
        if rec.status != "verified":
            return False
        rec.status = "consumed"
        return True

    async def find_user_by_identifier(self, identifier):
        return self.users.get(identifier)

    async def link_identifier(self, user_id, identifier):
        # Mismo contrato que el SQL: primero 'ya tenía uno', después 'lo tiene otro'
        if any(u.id == user_id for u in self.users.values()):
            return "already_linked"
        if identifier in self.users:
            return "taken"
        self.users[identifier] = UserRef(user_id, True)
        return "ok"


class FakeSovra:
    def __init__(self):
        self.created = []
        self.state = {"status": "pending"}
        self.raise_on_get = None

    async def create_verification(self, dcql):
        self.created.append(dcql)
        return {"session_id": "sov-1", "authorization_request_uri_ref": "openid4vp://ref",
                "authorization_request_uri": "openid4vp://long"}

    async def get_verification(self, session_id):
        if self.raise_on_get:
            raise self.raise_on_get
        return self.state


def completed(dni="12345678", issuer=ISSUER_URL):
    entry = {"id": "login", "claims": {"dni": dni}}
    if issuer:
        entry["iss"] = issuer
    return {"status": "completed", "presentation_data": {"credentials": [entry]}}


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class PureFunctions(unittest.TestCase):
    def test_normalize_dni(self):
        self.assertEqual(normalize_dni("12.345.678"), "12345678")
        self.assertEqual(normalize_dni(" 12345678 "), "12345678")
        self.assertEqual(normalize_dni(12345678), "12345678")
        for bad in (None, "", "abc", "123", "12345678901", {"a": 1}, ["1"], True, "12345678x"):
            self.assertIsNone(normalize_dni(bad), bad)

    def test_build_dcql_pide_solo_el_claim_y_fija_el_tipo(self):
        d = build_login_dcql("dni", "EmpleadoPublico")["credentials"][0]
        self.assertEqual(d["claims"], [{"path": ["dni"]}])
        self.assertEqual(d["meta"], {"vct_values": ["EmpleadoPublico"]})
        self.assertNotIn("meta", build_login_dcql("dni", "")["credentials"][0])

    def test_extract_presented_formas(self):
        self.assertEqual(extract_presented({"credentials": [{"claims": {"dni": "1"}, "iss": "X"}]}, "dni"), ("1", "X"))
        self.assertEqual(extract_presented({"credentials": {"login": {"claims": {"dni": "2"}}}}, "dni"), ("2", None))
        self.assertEqual(extract_presented({"claims": {"dni": "3"}}, "dni"), ("3", None))
        self.assertEqual(extract_presented({"dni": "4", "issuer": "Y"}, "dni"), ("4", "Y"))
        for bad in (None, {}, [], "x", {"credentials": []}, {"credentials": [{"claims": {"otro": "1"}}]}):
            self.assertEqual(extract_presented(bad, "dni"), (None, None))

    def test_issuer_matches(self):
        self.assertTrue(issuer_matches(ISSUER_URL, ISSUER_DID))
        self.assertTrue(issuer_matches(ISSUER_URL + "/", ISSUER_DID))
        self.assertTrue(issuer_matches(ISSUER_DID, ISSUER_DID))
        self.assertFalse(issuer_matches("https://x.com/did:sovra:0xabcd", ISSUER_DID))  # sufijo no es el DID
        self.assertFalse(issuer_matches("https://x.com/did:sovra:0xevil", ISSUER_DID))
        self.assertFalse(issuer_matches(None, ISSUER_DID))
        self.assertFalse(issuer_matches(ISSUER_URL, ""))


class LoginFlow(unittest.IsolatedAsyncioTestCase):
    def make(self, users=None, **cfg_over):
        self.store = FakeStore(users if users is not None else {"12345678": UserRef("u1", True)})
        self.sovra = FakeSovra()
        self.clock = Clock()
        self.svc = SovraLoginService(self.store, self.sovra, cfg(**cfg_over), self.clock)
        return self.svc

    async def start(self):
        r = await self.svc.start("1.2.3.4", "UA")
        return r

    async def test_start_usa_uri_corta_y_guarda_solo_el_hash(self):
        self.make()
        r = await self.start()
        self.assertEqual(r.uri, "openid4vp://ref")
        self.assertEqual(r.expires_at, T0 + timedelta(seconds=180))
        rec = self.store.rows[r.login_id]
        self.assertEqual(rec.poll_secret_hash, hash_poll_secret(r.poll_secret))
        self.assertNotIn(r.poll_secret, json.dumps(rec.__dict__, default=str))
        self.assertEqual(self.sovra.created[0]["credentials"][0]["meta"], {"vct_values": ["EmpleadoPublico"]})

    async def test_ttl_se_acota_al_maximo_de_sovra(self):
        self.make(SOVRA_LOGIN_TTL_SECONDS=99999)
        r = await self.start()
        self.assertEqual(r.expires_at, T0 + timedelta(seconds=600))

    async def test_start_sin_uri_falla(self):
        self.make()

        async def bad(dcql):
            return {"session_id": "x"}
        self.sovra.create_verification = bad
        with self.assertRaises(SovraError):
            await self.start()

    async def test_secreto_incorrecto_o_login_inexistente_dan_none(self):
        self.make()
        r = await self.start()
        self.assertIsNone(await self.svc.poll(r.login_id, "otro"))
        self.assertIsNone(await self.svc.poll(r.login_id, ""))
        self.assertIsNone(await self.svc.poll("no-existe", r.poll_secret))

    async def test_pendiente(self):
        self.make()
        r = await self.start()
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("pending"))

    async def test_login_ok_y_un_solo_uso(self):
        self.make()
        r = await self.start()
        self.sovra.state = completed()
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("ok", user_id="u1"))
        self.assertEqual(self.store.rows[r.login_id].status, "consumed")
        # Repetir la consulta no vuelve a entregar
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("failed"))

    async def test_dos_consultas_simultaneas_entregan_una_sola_vez(self):
        self.make()
        r = await self.start()
        self.sovra.state = completed()
        results = await asyncio.gather(*[self.svc.poll(r.login_id, r.poll_secret) for _ in range(5)])
        self.assertEqual(sum(1 for x in results if x.status == "ok"), 1)

    async def test_dni_con_puntos_encuentra_al_usuario(self):
        self.make()
        r = await self.start()
        self.sovra.state = completed(dni="12.345.678")
        self.assertEqual((await self.svc.poll(r.login_id, r.poll_secret)).status, "ok")

    async def test_rechazos_se_ven_igual_desde_afuera_pero_se_distinguen_en_el_log(self):
        casos = [
            ("dni sin usuario", {"99999999": UserRef("u9", True)}, completed(), "no_user_for_identifier"),
            ("usuario inactivo", {"12345678": UserRef("u1", False)}, completed(), "user_inactive"),
            ("sin dni en la presentacion", None, {"status": "completed", "presentation_data": {}}, "no_identifier_in_presentation"),
            ("dni invalido", None, completed(dni="abc"), "no_identifier_in_presentation"),
            ("sovra failed", None, {"status": "failed", "error": "credential_revoked"}, "sovra_failed:credential_revoked"),
        ]
        for nombre, users, sov_state, motivo in casos:
            with self.subTest(nombre):
                self.make(users=users)
                r = await self.start()
                self.sovra.state = sov_state
                self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("failed"))
                self.assertEqual(self.store.rows[r.login_id].error, motivo)
                self.assertIsNone(self.store.rows[r.login_id].user_id)

    async def test_pin_de_emisor(self):
        casos = [
            ("coincide", completed(issuer=ISSUER_URL), "ok"),
            ("otro emisor", completed(issuer="https://x.com/did:sovra:0xevil"), "failed"),
            ("Sovra no informa emisor: falla cerrado", completed(issuer=None), "failed"),
        ]
        for nombre, state, esperado in casos:
            with self.subTest(nombre):
                self.make(SOVRA_LOGIN_ISSUER_DID=ISSUER_DID)
                r = await self.start()
                self.sovra.state = state
                self.assertEqual((await self.svc.poll(r.login_id, r.poll_secret)).status, esperado)

    async def test_sin_pin_de_emisor_no_se_exige_emisor(self):
        self.make()
        r = await self.start()
        self.sovra.state = completed(issuer=None)
        self.assertEqual((await self.svc.poll(r.login_id, r.poll_secret)).status, "ok")

    async def test_vencimiento_propio(self):
        self.make()
        r = await self.start()
        self.clock.now = T0 + timedelta(seconds=181)
        self.sovra.state = completed()  # aunque Sovra diga completed, ya venció el intento
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("expired"))
        self.assertEqual(self.store.rows[r.login_id].status, "expired")
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("expired"))

    async def test_sesion_vencida_en_sovra(self):
        self.make()
        r = await self.start()
        self.sovra.state = {"status": "expired"}
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("expired"))

    async def test_error_transitorio_de_sovra_deja_el_intento_vivo(self):
        self.make()
        r = await self.start()
        self.sovra.raise_on_get = SovraError("timeout")
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("pending"))
        self.sovra.raise_on_get = None
        self.sovra.state = completed()
        self.assertEqual((await self.svc.poll(r.login_id, r.poll_secret)).status, "ok")

    async def test_estado_desconocido_de_sovra_sigue_pendiente(self):
        self.make()
        r = await self.start()
        self.sovra.state = {"status": "algo_nuevo"}
        self.assertEqual(await self.svc.poll(r.login_id, r.poll_secret), PollResult("pending"))

    async def test_un_intento_fallido_no_se_reabre(self):
        self.make(users={})
        r = await self.start()
        self.sovra.state = completed()
        self.assertEqual((await self.svc.poll(r.login_id, r.poll_secret)).status, "failed")
        # Aunque ahora exista el usuario, ese intento ya quedó cerrado
        self.store.users["12345678"] = UserRef("u1", True)
        self.assertEqual((await self.svc.poll(r.login_id, r.poll_secret)).status, "failed")


class LinkFlow(unittest.IsolatedAsyncioTestCase):
    """Un usuario ya logueado vincula el DNI de su credencial a su cuenta."""

    def make(self, users=None, **cfg_over):
        self.store = FakeStore(users if users is not None else {})
        self.sovra = FakeSovra()
        self.clock = Clock()
        self.svc = SovraLoginService(self.store, self.sovra, cfg(**cfg_over), self.clock)

    async def link_start(self, user_id="u1"):
        return await self.svc.start("1.2.3.4", "UA", purpose="link", user_id=user_id)

    async def link_poll(self, r, user_id="u1"):
        return await self.svc.poll(r.login_id, r.poll_secret, purpose="link", user_id=user_id)

    async def test_vincula_el_dni_de_la_credencial_al_usuario_del_token(self):
        self.make()
        r = await self.link_start()
        rec = self.store.rows[r.login_id]
        self.assertEqual((rec.purpose, rec.link_user_id), ("link", "u1"))
        self.sovra.state = completed(dni="12.345.678")
        self.assertEqual(await self.link_poll(r), PollResult("ok", user_id="u1"))
        self.assertEqual(self.store.users["12345678"].id, "u1")
        # Un solo uso
        self.assertEqual((await self.link_poll(r)).status, "failed")

    async def test_dni_de_otro_usuario_informa_taken(self):
        self.make(users={"12345678": UserRef("u2", True)})
        r = await self.link_start("u1")
        self.sovra.state = completed()
        res = await self.link_poll(r, "u1")
        self.assertEqual((res.status, res.reason), ("failed", "taken"))
        self.assertEqual(self.store.users["12345678"].id, "u2")  # no se tocó
        # El motivo también se informa en consultas posteriores
        self.assertEqual((await self.link_poll(r, "u1")).reason, "taken")

    async def test_usuario_con_dni_ya_vinculado_no_puede_cambiarlo(self):
        self.make(users={"11111111": UserRef("u1", True)})
        r = await self.link_start("u1")
        self.sovra.state = completed(dni="22222222")
        res = await self.link_poll(r, "u1")
        self.assertEqual((res.status, res.reason), ("failed", "already_linked"))
        self.assertNotIn("22222222", self.store.users)

    async def test_el_emisor_tambien_se_exige_al_vincular(self):
        self.make(SOVRA_LOGIN_ISSUER_DID=ISSUER_DID)
        r = await self.link_start()
        self.sovra.state = completed(issuer="https://x.com/did:sovra:0xevil")
        res = await self.link_poll(r)
        self.assertEqual((res.status, res.reason), ("failed", None))  # sin motivo detallado
        self.assertEqual(self.store.users, {})

    async def test_un_intento_de_vincular_no_se_cobra_como_login_ni_al_reves(self):
        self.make(users={"12345678": UserRef("u1", True)})
        link = await self.link_start("u2")
        self.sovra.state = completed()
        self.assertIsNone(await self.svc.poll(link.login_id, link.poll_secret, purpose="login"))
        login = await self.svc.start("1.2.3.4", "UA")
        self.assertIsNone(await self.svc.poll(login.login_id, login.poll_secret, purpose="link", user_id="u1"))
        self.assertEqual(self.store.rows[link.login_id].status, "pending")  # ni se tocó

    async def test_otro_usuario_no_puede_consultar_un_intento_ajeno(self):
        self.make()
        r = await self.link_start("u1")
        self.sovra.state = completed()
        self.assertIsNone(await self.link_poll(r, "u2"))
        self.assertIsNone(await self.link_poll(r, None))

    async def test_start_valida_proposito_y_usuario(self):
        self.make()
        for kw in (dict(purpose="link", user_id=None), dict(purpose="login", user_id="u1"),
                   dict(purpose="otro", user_id=None)):
            with self.assertRaises(ValueError, msg=kw):
                await self.svc.start("1.2.3.4", "UA", **kw)

    async def test_login_rechazado_no_expone_motivo(self):
        # En 'login' nadie está autenticado todavía: el motivo no sale nunca
        self.make(users={})
        r = await self.svc.start("1.2.3.4", "UA")
        self.sovra.state = completed()
        res = await self.svc.poll(r.login_id, r.poll_secret)
        self.assertEqual((res.status, res.reason), ("failed", None))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        return SovraClient(base_url="https://sovra.test", api_key="sovra_sk_SECRET", timeout=1,
                           transport=httpx.MockTransport(handler))

    def test_base_url_solo_https_o_localhost(self):
        for ok in ("https://api.sovra.io", "http://localhost:4000", "http://127.0.0.1:4000"):
            SovraClient(base_url=ok, api_key="k")
        for bad in ("http://api.sovra.io", "ftp://x.com", "", "https://"):
            with self.assertRaises(SovraError, msg=bad):
                SovraClient(base_url=bad, api_key="k")

    async def test_envia_bearer_y_dcql(self):
        seen = {}

        def handler(req: httpx.Request):
            seen["auth"] = req.headers["authorization"]
            seen["url"] = str(req.url)
            seen["body"] = json.loads(req.content)
            return httpx.Response(201, json={"session_id": "s"})

        out = await self.client(handler).create_verification({"credentials": []})
        self.assertEqual(out, {"session_id": "s"})
        self.assertEqual(seen["auth"], "Bearer sovra_sk_SECRET")
        self.assertEqual(seen["url"], "https://sovra.test/api/v1/verifier/verifications")
        self.assertEqual(seen["body"], {"dcql_query": {"credentials": []}})

    async def test_errores_no_filtran_la_key_ni_el_cuerpo(self):
        def handler(req):
            return httpx.Response(401, json={"error": "invalid_api_key", "echo": "sovra_sk_SECRET"})

        with self.assertRaises(SovraError) as cm:
            await self.client(handler).get_verification("abc")
        self.assertEqual(cm.exception.status, 401)
        self.assertIn("invalid_api_key", str(cm.exception))
        self.assertNotIn("sovra_sk_SECRET", str(cm.exception))

    async def test_error_de_red_no_filtra_la_url(self):
        def handler(req):
            raise httpx.ConnectError("no route to https://sovra.test/secret-path")

        with self.assertRaises(SovraError) as cm:
            await self.client(handler).get_verification("abc")
        self.assertNotIn("secret-path", str(cm.exception))

    async def test_respuesta_no_json_o_no_objeto(self):
        for resp in (httpx.Response(200, text="<html>"), httpx.Response(200, json=[1])):
            with self.assertRaises(SovraError):
                await self.client(lambda req, r=resp: r).get_verification("abc")


if __name__ == "__main__":
    unittest.main()
