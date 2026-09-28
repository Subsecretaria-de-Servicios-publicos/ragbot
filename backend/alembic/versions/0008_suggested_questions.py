"""suggested_questions

Preguntas disparadoras (hasta 3) por chatbot, mostradas como botones al inicio del chat.

Revision ID: 0008_suggested_questions
Revises: 0007_bot_api_key_and_usage
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0008_suggested_questions'
down_revision: Union[str, None] = '0007_bot_api_key_and_usage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chatbots', sa.Column('suggested_questions', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('chatbots', 'suggested_questions')
