"""fix_missing_0002_columns

Revision ID: 0002_fix_columns
Revises: 0001_initial
Create Date: 2026-04-29 13:32:07.919800

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_fix_columns'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0001_initial creó la columna 'metadata' en 'document_chunks'.
    # bf8698e9f336 (otra rama de 0001_initial) la renombra a 'chunk_metadata'.
    # Esta migración 0002_fix_columns estaba missing y causaba error de branch.
    # Se deja como placeholder para satisfacer el historial de Alembic.
    pass


def downgrade() -> None:
    pass
