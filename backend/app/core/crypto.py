"""app/core/crypto.py — Cifrado simétrico para secretos guardados en la BD (API keys de proveedores)."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    # Deriva una key Fernet válida (32 bytes urlsafe-base64) a partir del SECRET_KEY de la app,
    # para no depender de una variable de entorno más.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("No se pudo descifrar el secreto (SECRET_KEY cambió o el dato está corrupto)")
