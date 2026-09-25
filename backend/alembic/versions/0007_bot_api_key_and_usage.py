"""bot_api_key_and_usage

API key propia (cifrada) por chatbot y contadores para el límite mensual de tokens.

Revision ID: 0007_bot_api_key_and_usage
Revises: 0006_org_logo_url
Create Date: 2026-09-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007_bot_api_key_and_usage'
down_revision: Union[str, None] = '0006_org_logo_url'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chatbots', sa.Column('ai_api_key_encrypted', sa.Text(), nullable=True))
    op.add_column('chatbots', sa.Column('ai_api_key_hint', sa.String(length=8), nullable=True))
    op.add_column('chatbots', sa.Column('ai_api_key_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('chatbots', sa.Column('ai_api_key_updated_by', sa.String(length=36), nullable=True))
    op.add_column('chatbots', sa.Column('monthly_token_limit', sa.BigInteger(), nullable=True))
    op.add_column('chatbots', sa.Column('usage_month', sa.String(length=7), nullable=True))
    op.add_column('chatbots', sa.Column('usage_month_tokens', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('chatbots', sa.Column('usage_alert_level', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    for col in ('usage_alert_level', 'usage_month_tokens', 'usage_month', 'monthly_token_limit',
                'ai_api_key_updated_by', 'ai_api_key_updated_at', 'ai_api_key_hint', 'ai_api_key_encrypted'):
        op.drop_column('chatbots', col)
