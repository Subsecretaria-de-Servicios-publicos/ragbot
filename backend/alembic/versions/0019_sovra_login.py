"""sovra_login

Login al dashboard con credencial de Sovra ID: users.sovra_identifier (DNI con el que se busca al
usuario) y sovra_login_sessions (un intento de login o de vinculación del DNI, de un solo uso).

Revision ID: 0019_sovra_login
Revises: 0018_web_search
Create Date: 2026-11-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0019_sovra_login'
down_revision: Union[str, None] = '0018_web_search'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    user_cols = {c['name'] for c in insp.get_columns('users')}
    if 'sovra_identifier' not in user_cols:
        op.add_column('users', sa.Column('sovra_identifier', sa.String(20), nullable=True))
        op.create_unique_constraint('uq_users_sovra_identifier', 'users', ['sovra_identifier'])

    if 'sovra_login_sessions' not in insp.get_table_names():
        op.create_table(
            'sovra_login_sessions',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('sovra_session_id', sa.String(36), nullable=False),
            sa.Column('poll_secret_hash', sa.String(64), nullable=False),
            sa.Column('purpose', sa.String(10), nullable=False, server_default='login'),
            sa.Column('link_user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('error', sa.String(100), nullable=True),
            sa.Column('ip_address', sa.String(45), nullable=True),
            sa.Column('user_agent', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_sovra_login_sessions_expires_at', 'sovra_login_sessions', ['expires_at'])


def downgrade() -> None:
    op.drop_table('sovra_login_sessions')
    op.drop_constraint('uq_users_sovra_identifier', 'users', type_='unique')
    op.drop_column('users', 'sovra_identifier')
