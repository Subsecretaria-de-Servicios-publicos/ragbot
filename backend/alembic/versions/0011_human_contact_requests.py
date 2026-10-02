"""human_contact_requests

Formulario de "hablar con una persona": nombre, email y/o teléfono, y la consulta. Se guarda
para verlo desde el dashboard (por bot, y global para superadmin) y se avisa por mail.

Revision ID: 0011_human_contact_requests
Revises: 0010_chat_pdf_upload
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0011_human_contact_requests'
down_revision: Union[str, None] = '0010_chat_pdf_upload'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONTACT_STATUS_ENUM = sa.Enum('pending', 'resolved', name='contactrequeststatus')


def upgrade() -> None:
    CONTACT_STATUS_ENUM.create(op.get_bind(), checkfirst=True)
    op.create_table(
        'human_contact_requests',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('chatbot_id', sa.String(length=36), sa.ForeignKey('chatbots.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), sa.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('status', CONTACT_STATUS_ENUM, nullable=False, server_default='pending'),
        sa.Column('email_sent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_human_contact_requests_chatbot_id', 'human_contact_requests', ['chatbot_id'])
    op.create_index('ix_human_contact_requests_status', 'human_contact_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_human_contact_requests_status', table_name='human_contact_requests')
    op.drop_index('ix_human_contact_requests_chatbot_id', table_name='human_contact_requests')
    op.drop_table('human_contact_requests')
    CONTACT_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
