"""bot_forms

Formularios que arma el admin para que el bot le pida datos estructurados al usuario final
(ej. 'Certificado médico': DNI, nombre, adjuntar PDF). Los campos los define el admin —
bot_forms + bot_form_fields (el esquema) y bot_form_submissions + bot_form_submission_files
(las respuestas, que el staff revisa desde el dashboard).

Revision ID: 0016_bot_forms
Revises: 0015_token_cost
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0016_bot_forms'
down_revision: Union[str, None] = '0015_token_cost'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# contactrequeststatus ya existe (migración 0011): se reutiliza el mismo flujo pending/resolved.
CONTACT_STATUS_ENUM = postgresql.ENUM('pending', 'resolved', name='contactrequeststatus', create_type=False)
FIELD_TYPE_ENUM = postgresql.ENUM('text', 'number', 'email', 'file', name='formfieldtype', create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("""
        DO $$ BEGIN
            CREATE TYPE formfieldtype AS ENUM ('text', 'number', 'email', 'file');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    inspector = sa.inspect(bind)

    if not inspector.has_table('bot_forms'):
        op.create_table(
            'bot_forms',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('chatbot_id', sa.String(length=36), sa.ForeignKey('chatbots.id', ondelete='CASCADE'), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('success_message', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.String(length=36), nullable=True),
        )
        op.create_index('ix_bot_forms_chatbot_id', 'bot_forms', ['chatbot_id'])

    if not inspector.has_table('bot_form_fields'):
        op.create_table(
            'bot_form_fields',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('form_id', sa.String(length=36), sa.ForeignKey('bot_forms.id', ondelete='CASCADE'), nullable=False),
            sa.Column('key', sa.String(length=100), nullable=False),
            sa.Column('label', sa.String(length=200), nullable=False),
            sa.Column('field_type', FIELD_TYPE_ENUM, nullable=False),
            sa.Column('required', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('help_text', sa.String(length=300), nullable=True),
            sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        )
        op.create_index('ix_bot_form_fields_form_id', 'bot_form_fields', ['form_id'])

    if not inspector.has_table('bot_form_submissions'):
        op.create_table(
            'bot_form_submissions',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('form_id', sa.String(length=36), sa.ForeignKey('bot_forms.id', ondelete='CASCADE'), nullable=False),
            sa.Column('chatbot_id', sa.String(length=36), sa.ForeignKey('chatbots.id', ondelete='CASCADE'), nullable=False),
            sa.Column('conversation_id', sa.String(length=36), sa.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True),
            sa.Column('data', postgresql.JSONB(), nullable=False, server_default='{}'),
            sa.Column('status', CONTACT_STATUS_ENUM, nullable=False, server_default='pending'),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('resolved_by', sa.String(length=36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_bot_form_submissions_form_id', 'bot_form_submissions', ['form_id'])
        op.create_index('ix_bot_form_submissions_chatbot_id', 'bot_form_submissions', ['chatbot_id'])
        op.create_index('ix_bot_form_submissions_status', 'bot_form_submissions', ['status'])

    if not inspector.has_table('bot_form_submission_files'):
        op.create_table(
            'bot_form_submission_files',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('submission_id', sa.String(length=36), sa.ForeignKey('bot_form_submissions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('field_key', sa.String(length=100), nullable=False),
            sa.Column('filename', sa.String(length=255), nullable=False),
            sa.Column('original_filename', sa.String(length=255), nullable=False),
            sa.Column('mime_type', sa.String(length=100), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_bot_form_submission_files_submission_id', 'bot_form_submission_files', ['submission_id'])


def downgrade() -> None:
    op.drop_table('bot_form_submission_files')
    op.drop_table('bot_form_submissions')
    op.drop_table('bot_form_fields')
    op.drop_table('bot_forms')
    op.get_bind().exec_driver_sql("DROP TYPE IF EXISTS formfieldtype")
