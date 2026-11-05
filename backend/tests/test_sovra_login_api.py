"""Pruebas de los endpoints /auth/sovra/*, /auth/methods, /auth/me y /users con una base falsa y Sovra simulado.

Correr desde backend/:  ./venv/bin/python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://u:p@localhost/db")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import routers  # noqa: E402
from app.core.security import create_access_token, decode_token  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import UserRole  # noqa: E402
from app.services.sovra_login import SovraLoginService, UserRef  # noqa: E402

# Reusa los dobles de test_sovra_login.py
sys.path.insert(0, os.path.dirname(__file__))
from test_sovra_login import FakeSovra, FakeStore, cfg, completed  # noqa: E402

BASE = "/api/v1/auth/sovra"


def make_user(uid="u1", role=UserRole.operator, identifier=None, **kw):
    return SimpleNamespace(id=uid, username=f"user_{uid}", email=f"{uid}@x.com", full_name=f"Nombre {uid}",
                           role=role, is_active=True, sovra_identifier=identifier, **kw)


def bearer(user):
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": user.id, "username": user.username, "role": user.role.value})}


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    """Lo mínimo que usan los endpoints: db.get(User, id), execute(...) con filas configurables
    (listado de usuarios, chequeo de DNI duplicado, update de last_login) y commit()."""

    def __init__(self, *users):
        self.users = {u.id: u for u in users}
        self.rows = []  # lo que devuelve execute()
        self.commits = 0

    async def get(self, model, pk):
        return self.users.get(pk)

    async def execute(self, stmt):
        return FakeResult(self.rows)

    async def commit(self):
        self.commits += 1


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.user = make_user("u1")
        self.db = FakeDB(self.user)
        self.store = FakeStore({"12345678": UserRef("u1", True)})
        self.sovra = FakeSovra()
        self.svc = SovraLoginService(self.store, self.sovra, cfg())

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.patches = [
            mock.patch.object(routers.settings, "SOVRA_LOGIN_ENABLED", True),
            mock.patch.object(routers, "_sovra_login_service", lambda db: self.svc),
            mock.patch.object(routers, "_sovra_start_rate_limit", mock.AsyncMock()),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        app.dependency_overrides.clear()

    def start(self, path="/start", headers=None):
        r = self.client.post(f"{BASE}{path}", headers=headers)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()


class SovraLoginApi(ApiTestCase):
    def test_start_devuelve_lo_que_necesita_el_navegador(self):
        body = self.start()
        self.assertEqual(set(body), {"login_id", "poll_secret", "authorization_request_uri", "qr_data_uri",
                                     "expires_at", "ttl_seconds"})
        self.assertEqual(body["authorization_request_uri"], "openid4vp://ref")
        self.assertTrue(body["qr_data_uri"].startswith("data:image/svg+xml"))
        self.assertGreater(body["ttl_seconds"], 0)

    def test_methods_informa_si_sovra_esta_disponible(self):
        with mock.patch.object(routers, "_sovra_login_configured", lambda: True):
            self.assertEqual(self.client.get("/api/v1/auth/methods").json(), {"password": True, "sovra": True})
        with mock.patch.object(routers, "_sovra_login_configured", lambda: False):
            self.assertEqual(self.client.get("/api/v1/auth/methods").json(), {"password": True, "sovra": False})

    def test_estado_pendiente_y_secreto_en_header(self):
        s = self.start()
        r = self.client.get(f"{BASE}/{s['login_id']}", headers={"X-Poll-Secret": s["poll_secret"]})
        self.assertEqual((r.status_code, r.json()), (200, {"status": "pending"}))

    def test_sin_secreto_o_con_secreto_ajeno_es_404(self):
        s = self.start()
        self.assertEqual(self.client.get(f"{BASE}/{s['login_id']}").status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}/{s['login_id']}", headers={"X-Poll-Secret": "x"}).status_code, 404)
        # El secreto en la URL no sirve
        self.assertEqual(self.client.get(f"{BASE}/{s['login_id']}?poll_secret={s['poll_secret']}").status_code, 404)

    def test_login_ok_emite_los_mismos_jwt_que_el_login_normal(self):
        s = self.start()
        self.sovra.state = completed()
        r = self.client.get(f"{BASE}/{s['login_id']}", headers={"X-Poll-Secret": s["poll_secret"]})
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual((body["role"], body["user_id"], body["token_type"]), ("operator", "u1", "bearer"))
        access = decode_token(body["access_token"])
        self.assertEqual((access["sub"], access["type"], access["role"]), ("u1", "access", "operator"))
        self.assertEqual(decode_token(body["refresh_token"])["type"], "refresh")
        self.assertGreaterEqual(self.db.commits, 1)  # last_login registrado

    def test_segundo_canje_no_entrega_tokens(self):
        s = self.start()
        self.sovra.state = completed()
        h = {"X-Poll-Secret": s["poll_secret"]}
        self.assertEqual(self.client.get(f"{BASE}/{s['login_id']}", headers=h).json()["status"], "ok")
        self.assertEqual(self.client.get(f"{BASE}/{s['login_id']}", headers=h).json(), {"status": "failed"})

    def test_usuario_desactivado_entre_verificacion_y_entrega(self):
        s = self.start()
        self.sovra.state = completed()
        self.user.is_active = False  # el store todavía lo ve activo, pero la base ya no
        r = self.client.get(f"{BASE}/{s['login_id']}", headers={"X-Poll-Secret": s["poll_secret"]})
        self.assertEqual(r.json(), {"status": "failed"})

    def test_rechazo_no_revela_el_motivo(self):
        self.store.users.clear()
        s = self.start()
        self.sovra.state = completed()
        r = self.client.get(f"{BASE}/{s['login_id']}", headers={"X-Poll-Secret": s["poll_secret"]})
        self.assertEqual(r.json(), {"status": "failed"})


class SovraLinkApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.store.users.clear()  # nadie tiene DNI vinculado todavía
        self.h = bearer(self.user)

    def poll(self, s, headers=None, path="/link"):
        h = {"X-Poll-Secret": s["poll_secret"], **(self.h if headers is None else headers)}
        return self.client.get(f"{BASE}{path}/{s['login_id']}", headers=h)

    def test_exige_estar_logueado(self):
        r = self.client.post(f"{BASE}/link/start")
        self.assertIn(r.status_code, (401, 403))
        s = self.start("/link/start", self.h)
        r = self.client.get(f"{BASE}/link/{s['login_id']}", headers={"X-Poll-Secret": s["poll_secret"]})
        self.assertIn(r.status_code, (401, 403))

    def test_el_usuario_sale_del_token(self):
        s = self.start("/link/start", self.h)
        rec = self.store.rows[s["login_id"]]
        self.assertEqual((rec.purpose, rec.link_user_id), ("link", "u1"))

    def test_vincula_el_dni_y_no_entrega_tokens(self):
        s = self.start("/link/start", self.h)
        self.sovra.state = completed(dni="12345678")
        r = self.poll(s)
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        self.assertEqual(self.store.users["12345678"].id, "u1")

    def test_motivos_de_rechazo_para_el_usuario_logueado(self):
        self.store.users["12345678"] = UserRef("u2", True)
        s = self.start("/link/start", self.h)
        self.sovra.state = completed()
        self.assertEqual(self.poll(s).json(), {"status": "failed", "reason": "taken"})

        self.store.users.clear()
        self.store.users["99999999"] = UserRef("u1", True)  # u1 ya tiene otro DNI
        s = self.start("/link/start", self.h)
        self.assertEqual(self.poll(s).json(), {"status": "failed", "reason": "already_linked"})

    def test_otro_usuario_no_puede_consultar_mi_intento(self):
        other = make_user("u2")
        self.db.users["u2"] = other
        s = self.start("/link/start", self.h)
        self.assertEqual(self.poll(s, headers=bearer(other)).status_code, 404)

    def test_un_intento_de_login_no_se_consulta_como_vinculacion_ni_al_reves(self):
        login = self.start("/start")
        self.assertEqual(self.poll(login).status_code, 404)  # /link/{id} con un intento de login
        link = self.start("/link/start", self.h)
        self.sovra.state = completed(dni="12345678")
        r = self.client.get(f"{BASE}/{link['login_id']}", headers={"X-Poll-Secret": link["poll_secret"]})
        self.assertEqual(r.status_code, 404)  # /{id} con un intento de vinculación: no entrega tokens
        self.assertEqual(self.store.users, {})  # y no se vinculó nada

    def test_me_informa_si_ya_vinculo(self):
        self.assertFalse(self.client.get("/api/v1/auth/me", headers=self.h).json()["sovra_linked"])
        self.user.sovra_identifier = "12345678"
        self.assertTrue(self.client.get("/api/v1/auth/me", headers=self.h).json()["sovra_linked"])


class UsersApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("a1", UserRole.admin)
        self.superu = make_user("s1", UserRole.superadmin, identifier="12345678")
        self.db.users.update({"a1": self.admin, "s1": self.superu})

    def test_listado_incluye_full_name_y_dni_solo_para_superadmin(self):
        self.db.rows = [self.superu, self.user]
        sup = self.client.get("/api/v1/users/", headers=bearer(self.superu)).json()
        self.assertEqual(sup[0]["sovra_identifier"], "12345678")
        self.assertEqual((sup[0]["full_name"], sup[0]["has_sovra_id"], sup[1]["has_sovra_id"]),
                         ("Nombre s1", True, False))
        adm = self.client.get("/api/v1/users/", headers=bearer(self.admin)).json()
        self.assertNotIn("sovra_identifier", adm[0])  # el admin ve que hay uno, no cuál
        self.assertEqual((adm[0]["has_sovra_id"], adm[1]["has_sovra_id"]), (True, False))

    def patch(self, data, who=None):
        who = who or self.superu
        return self.client.patch(f"/api/v1/users/{self.user.id}", json=data, headers=bearer(who))

    def test_patch_normaliza_el_dni(self):
        self.db.rows = []  # nadie más lo tiene
        self.assertEqual(self.patch({"sovra_identifier": "12.345.678"}).status_code, 200)
        self.assertEqual(self.user.sovra_identifier, "12345678")

    def test_patch_dni_vacio_lo_quita(self):
        self.user.sovra_identifier = "12345678"
        self.assertEqual(self.patch({"sovra_identifier": ""}).status_code, 200)
        self.assertIsNone(self.user.sovra_identifier)

    def test_patch_dni_invalido_es_422_y_repetido_es_409(self):
        self.assertEqual(self.patch({"sovra_identifier": "abc"}).status_code, 422)
        self.assertIsNone(self.user.sovra_identifier)
        self.db.rows = [("otro-usuario",)]
        self.assertEqual(self.patch({"sovra_identifier": "12345678"}).status_code, 409)
        self.assertIsNone(self.user.sovra_identifier)

    def test_solo_superadmin_edita(self):
        self.assertEqual(self.patch({"sovra_identifier": "12345678"}, who=self.admin).status_code, 403)


class SovraLoginApiApagado(unittest.TestCase):
    def test_methods_apagado_no_ofrece_sovra_aunque_este_configurado(self):
        with mock.patch.object(routers.settings, "SOVRA_LOGIN_ENABLED", False), \
             mock.patch.object(routers, "_sovra_login_configured", lambda: True):
            self.assertEqual(TestClient(app).get("/api/v1/auth/methods").json(), {"password": True, "sovra": False})

    def test_apagado_es_404_y_no_toca_a_sovra(self):
        with mock.patch.object(routers.settings, "SOVRA_LOGIN_ENABLED", False):
            c = TestClient(app)
            self.assertEqual(c.post(f"{BASE}/start").status_code, 404)
            self.assertEqual(c.get(f"{BASE}/abc").status_code, 404)

    def test_vincular_apagado_es_404_aunque_este_logueado(self):
        user = make_user("u1")

        async def fake_db():
            yield FakeDB(user)
        app.dependency_overrides[get_db] = fake_db
        try:
            with mock.patch.object(routers.settings, "SOVRA_LOGIN_ENABLED", False):
                c = TestClient(app)
                self.assertEqual(c.post(f"{BASE}/link/start", headers=bearer(user)).status_code, 404)
                self.assertEqual(c.get(f"{BASE}/link/abc", headers=bearer(user)).status_code, 404)
        finally:
            app.dependency_overrides.clear()

    def test_activo_pero_sin_configurar_es_503(self):
        async def fake_db():
            yield FakeDB()
        app.dependency_overrides[get_db] = fake_db
        try:
            with mock.patch.object(routers.settings, "SOVRA_LOGIN_ENABLED", True), \
                 mock.patch.object(routers.settings, "SOVRA_BASE_URL", "https://x.test"), \
                 mock.patch.object(routers.settings, "SOVRA_API_KEY", "k"), \
                 mock.patch.object(routers.settings, "SOVRA_LOGIN_VCT", ""):  # falta el tipo de credencial
                self.assertEqual(TestClient(app).post(f"{BASE}/start").status_code, 503)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
