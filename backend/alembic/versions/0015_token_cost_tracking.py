"""token_cost_tracking

Desglose del consumo (entrada, salida, embeddings) y costo estimado en USD, por mensaje y por bot.

Revision ID: 0015_token_cost
Revises: 0014_contact_resolver
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0015_token_cost'
down_revision: Union[str, None] = '0014_contact_resolver'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOT_COLUMNS = [
    sa.Column('total_prompt_tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('total_completion_tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('total_embedding_tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('total_cost_usd', sa.Numeric(18, 10), server_default='0', nullable=False),
    sa.Column('usage_month_cost_usd', sa.Numeric(18, 10), server_default='0', nullable=False),
]


def upgrade() -> None:
    for col in BOT_COLUMNS:
        op.add_column('chatbots', col.copy())
    op.add_column('messages', sa.Column('embedding_tokens', sa.Integer(), server_default='0', nullable=False))
    op.add_column('messages', sa.Column('cost_usd', sa.Numeric(14, 10), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'cost_usd')
    op.drop_column('messages', 'embedding_tokens')
    for col in reversed(BOT_COLUMNS):
        op.drop_column('chatbots', col.name)
