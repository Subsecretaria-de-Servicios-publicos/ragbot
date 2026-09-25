"""ai_provider_configs

Revision ID: 0004_ai_provider_configs
Revises: 0003_merge_heads
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004_ai_provider_configs'
down_revision: Union[str, None] = '0003_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_type=False: el tipo 'aiprovider' ya existe (lo creó 0001_initial para chatbots.ai_provider)
    aiprovider_enum = postgresql.ENUM(
        'openai', 'anthropic', 'google', 'ollama', name='aiprovider', create_type=False
    )
    op.create_table(
        'ai_provider_configs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('provider', aiprovider_enum, nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('base_url', sa.String(length=500), nullable=True),
        sa.Column('models', postgresql.JSONB(), nullable=True),
        sa.Column('models_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', name='uq_ai_provider_configs_provider'),
    )


def downgrade() -> None:
    op.drop_table('ai_provider_configs')
