"""app/services/sovra_login_store.py — LoginStore sobre SQLAlchemy (tablas sovra_login_sessions y users)."""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import SovraLoginSession, User
from app.services.sovra_login import LoginRecord, UserRef


def _to_record(row: SovraLoginSession) -> LoginRecord:
    return LoginRecord(
        id=row.id, sovra_session_id=row.sovra_session_id, poll_secret_hash=row.poll_secret_hash,
        expires_at=row.expires_at, status=row.status, purpose=row.purpose, link_user_id=row.link_user_id,
        user_id=row.user_id, error=row.error, ip_address=row.ip_address, user_agent=row.user_agent,
    )


class SqlLoginStore:
    # Cada método confirma su transacción: el estado del intento tiene que quedar guardado aunque
    # el request termine después con otra respuesta (get_db solo confirma si no hubo excepción).
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, rec: LoginRecord) -> None:
        self.db.add(SovraLoginSession(
            id=rec.id, sovra_session_id=rec.sovra_session_id, poll_secret_hash=rec.poll_secret_hash,
            status=rec.status, expires_at=rec.expires_at, purpose=rec.purpose,
            link_user_id=rec.link_user_id, ip_address=rec.ip_address, user_agent=rec.user_agent,
        ))
        await self.db.commit()

    async def get(self, login_id: str) -> Optional[LoginRecord]:
        row = await self.db.get(SovraLoginSession, login_id)
        return _to_record(row) if row else None

    async def update(self, login_id: str, **fields: Any) -> None:
        await self.db.execute(update(SovraLoginSession).where(SovraLoginSession.id == login_id).values(**fields))
        await self.db.commit()

    async def consume(self, login_id: str) -> bool:
        # El WHERE es el candado: si dos requests llegan a la vez, solo uno ve la fila en 'verified'
        res = await self.db.execute(
            update(SovraLoginSession)
            .where(SovraLoginSession.id == login_id, SovraLoginSession.status == "verified",
                   SovraLoginSession.consumed_at.is_(None))
            .values(status="consumed", consumed_at=datetime.now(timezone.utc))
            .returning(SovraLoginSession.id)
        )
        won = res.first() is not None
        await self.db.commit()
        return won

    async def link_identity(self, user_id: str, identifier: str, holder_did: str) -> str:
        # Las condiciones del WHERE son el candado: sin wallet vinculada (no se pisa una existente;
        # cambiarla es cosa de un admin) y con el DNI sin cargar o igual al de la credencial. Las
        # restricciones únicas de ambas columnas garantizan que dos usuarios no compartan DNI ni
        # wallet aunque dos vinculaciones corran a la vez: la perdedora falla con IntegrityError.
        try:
            res = await self.db.execute(
                update(User)
                .where(User.id == user_id, User.sovra_holder_did.is_(None),
                       or_(User.sovra_identifier.is_(None), User.sovra_identifier == identifier))
                .values(sovra_identifier=identifier, sovra_holder_did=holder_did).returning(User.id))
            if res.first() is not None:
                await self.db.commit()
                return "ok"
            row = (await self.db.execute(select(User.sovra_holder_did).where(User.id == user_id))).first()
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            return "taken"
        return "already_linked" if row and row.sovra_holder_did else "mismatch"

    async def find_user_by_holder(self, holder_did: str) -> Optional[UserRef]:
        res = await self.db.execute(
            select(User.id, User.is_active, User.sovra_identifier).where(User.sovra_holder_did == holder_did))
        row = res.first()
        return UserRef(id=row.id, is_active=row.is_active, identifier=row.sovra_identifier) if row else None
