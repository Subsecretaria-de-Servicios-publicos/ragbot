"""bot_files

PDFs descargables por bot (formularios, guías, etc.) que el bot ofrece como link cuando el
usuario los pide — distintos de los Document de la base de conocimiento (RAG).

Revision ID: 0012_bot_files
Revises: 0011_human_contact_requests
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0012_bot_files'
down_revision: Union[str, None] = '0011_human_contact_requests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bot_files',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('chatbot_id', sa.String(length=36), sa.ForeignKey('chatbots.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.String(length=36), nullable=True),
    )
    op.create_index('ix_bot_files_chatbot_id', 'bot_files', ['chatbot_id'])


def downgrade() -> None:
    op.drop_index('ix_bot_files_chatbot_id', table_name='bot_files')
    op.drop_table('bot_files')
