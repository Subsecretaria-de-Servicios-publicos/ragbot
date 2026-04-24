"""Merge migration branches

Revision ID: 0003_merge_heads
Revises: bf8698e9f336, 0002_fix_columns
Create Date: 2026-04-23
"""
from alembic import op

revision = '0003_merge_heads'
# FIX #6: ambas migraciones apuntaban a 0001_initial como parent → branch conflict
# Este merge las une en una sola cabeza
down_revision = ('bf8698e9f336', '0002_fix_columns')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # Solo unifica las ramas


def downgrade() -> None:
    pass
