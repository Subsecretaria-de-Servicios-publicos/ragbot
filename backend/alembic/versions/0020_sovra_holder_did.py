"""sovra_holder_did

Login con Sovra ID atado a la wallet: users.sovra_holder_did (holder_did de la wallet vinculada).
Va aparte de 0019 porque esa ya estaba aplicada en el servidor cuando se agregó la columna.

Revision ID: 0020_sovra_holder_did
Revises: 0019_sovra_login
Create Date: 2026-11-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0020_sovra_holder_did'
down_revision: Union[str, None] = '0019_sovra_login'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'sovra_holder_did' not in {c['name'] for c in insp.get_columns('users')}:
        op.add_column('users', sa.Column('sovra_holder_did', sa.String(255), nullable=True))
        op.create_unique_constraint('uq_users_sovra_holder_did', 'users', ['sovra_holder_did'])


def downgrade() -> None:
    op.drop_constraint('uq_users_sovra_holder_did', 'users', type_='unique')
    op.drop_column('users', 'sovra_holder_did')
