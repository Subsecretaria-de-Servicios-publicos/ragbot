"""
app/core/security.py — JWT, hashing de contraseñas, RBAC
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


# ─── Password ────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─── JWT ─────────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _decode_access_token(token: str) -> dict:
    """Decodifica y exige que sea específicamente un access token (no un refresh token)."""
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere un access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def _load_active_user(payload: dict, db: AsyncSession):
    """Revalida contra la BD que el usuario sigue existiendo y activo, y trae su rol actual
    (evita que un usuario desactivado o degradado siga operando con un token viejo)."""
    from app.models.models import User  # import local para evitar ciclos de import

    user = await db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o inexistente",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ─── Role-Based Access Control ───────────────────────────────
ROLE_HIERARCHY = {
    "superadmin": 4,
    "admin": 3,
    "operator": 2,
    "viewer": 1,
}


def require_role(minimum_role: str):
    """Decorador de dependencia FastAPI para control de acceso por rol.
    Revalida usuario activo y rol actual contra la BD en cada request."""
    async def checker(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: AsyncSession = Depends(get_db),
    ):
        payload = _decode_access_token(credentials.credentials)
        user = await _load_active_user(payload, db)
        if ROLE_HIERARCHY.get(user.role.value, 0) < ROLE_HIERARCHY.get(minimum_role, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol '{minimum_role}' o superior",
            )
        payload["role"] = user.role.value
        payload["sub"] = user.id
        return payload
    return checker


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    payload = _decode_access_token(credentials.credentials)
    user = await _load_active_user(payload, db)
    payload["role"] = user.role.value
    payload["sub"] = user.id
    return payload
