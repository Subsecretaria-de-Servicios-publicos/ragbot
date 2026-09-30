"""chat_pdf_upload

Permite que el usuario final suba un PDF en el chat (toggle por bot) y guarda el texto
extraído por conversación, para usarlo como contexto adicional en esa charla puntual.

Revision ID: 0010_chat_pdf_upload
Revises: 0009_bot_contact_info
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0010_chat_pdf_upload'
down_revision: Union[str, None] = '0009_bot_contact_info'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chatbots', sa.Column('allow_user_uploads', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('conversations', sa.Column('uploaded_doc_filename', sa.String(length=255), nullable=True))
    op.add_column('conversations', sa.Column('uploaded_doc_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'uploaded_doc_text')
    op.drop_column('conversations', 'uploaded_doc_filename')
    op.drop_column('chatbots', 'allow_user_uploads')
