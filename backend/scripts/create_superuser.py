"""
scripts/create_superuser.py — Crear superusuario inicial
Uso: python scripts/create_superuser.py
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import AsyncSessionLocal
from app.models.models import User, UserRole
from app.core.security import hash_password
from sqlalchemy import select


async def create_superuser():
    print("=== Crear SuperAdmin ===")
    email = input("Email: ").strip()
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    full_name = input("Nombre completo (opcional): ").strip() or None

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"❌ El email {email} ya existe")
            return

        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.superadmin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"✅ SuperAdmin creado: {username} ({email})")


if __name__ == "__main__":
    asyncio.run(create_superuser())
