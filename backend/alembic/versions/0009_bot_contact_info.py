"""bot_contact_info

Email y/o WhatsApp de contacto por chatbot, para escalar a intervención humana desde el chat.

Revision ID: 0009_bot_contact_info
Revises: 0008_suggested_questions
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0009_bot_contact_info'
down_revision: Union[str, None] = '0008_suggested_questions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chatbots', sa.Column('contact_email', sa.String(length=255), nullable=True))
    op.add_column('chatbots', sa.Column('contact_whatsapp', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('chatbots', 'contact_whatsapp')
    op.drop_column('chatbots', 'contact_email')
