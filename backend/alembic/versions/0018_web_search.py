"""web_search

Búsqueda en internet por bot (tool del proveedor de IA, no una integración propia). Solo
Anthropic respeta un tope de búsquedas por respuesta (web_search_max_uses); en Google y OpenAI
el campo se guarda pero no hay forma de hacerlo cumplir — ver ai_service.py.

Revision ID: 0018_web_search
Revises: 0017_knowledge_tables
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0018_web_search'
down_revision: Union[str, None] = '0017_knowledge_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    chatbot_cols = {c['name'] for c in sa.inspect(bind).get_columns('chatbots')}
    if 'allow_web_search' not in chatbot_cols:
        op.add_column('chatbots', sa.Column('allow_web_search', sa.Boolean(), nullable=False, server_default='false'))
    if 'web_search_max_uses' not in chatbot_cols:
        op.add_column('chatbots', sa.Column('web_search_max_uses', sa.Integer(), nullable=True))
    if 'total_web_searches' not in chatbot_cols:
        op.add_column('chatbots', sa.Column('total_web_searches', sa.BigInteger(), nullable=False, server_default='0'))

    message_cols = {c['name'] for c in sa.inspect(bind).get_columns('messages')}
    if 'web_searches' not in message_cols:
        op.add_column('messages', sa.Column('web_searches', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('messages', 'web_searches')
    op.drop_column('chatbots', 'total_web_searches')
    op.drop_column('chatbots', 'web_search_max_uses')
    op.drop_column('chatbots', 'allow_web_search')
