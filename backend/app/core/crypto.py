"""app/core/crypto.py — Cifrado simétrico para secretos guardados en la BD (API keys de proveedores y de bots)."""
import base64
import hashlib
import re

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


def _derive(secret: str) -> Fernet:
    # Deriva una key Fernet válida (32 bytes urlsafe-base64) a partir de un string cualquiera.
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet() -> MultiFernet:
    """Cifra con ENCRYPTION_KEY si está definida (así rotar SECRET_KEY —JWT— no destruye los
    secretos guardados, y un volcado de la BD solo no alcanza para descifrarlos). Descifra con
    ENCRYPTION_KEY y, como respaldo, con la derivada de SECRET_KEY: lo cifrado antes de definir
    ENCRYPTION_KEY sigue funcionando."""
    keys = []
    if settings.ENCRYPTION_KEY:
        keys.append(_derive(settings.ENCRYPTION_KEY))
    keys.append(_derive(settings.SECRET_KEY))
    return MultiFernet(keys)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("No se pudo descifrar el secreto (la clave de cifrado cambió o el dato está corrupto)")


# Patrones típicos de API keys: se tachan de logs, alertas y mensajes de error visibles.
_KEY_PATTERNS = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|rbk_[A-Za-z0-9_\-]{16,})"
)


def scrub_secrets(text: str) -> str:
    """Reemplaza cualquier cosa con forma de API key por '[redacted]'. Defensa en profundidad:
    un error del proveedor podría reflejar la key (o parte de ella) en su mensaje."""
    return _KEY_PATTERNS.sub("[redacted]", text or "")
