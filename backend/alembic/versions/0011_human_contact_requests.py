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
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0011_human_contact_requests'
down_revision: Union[str, None] = '0010_chat_pdf_upload'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# OJO: create_type=False solo funciona con postgresql.ENUM (el específico del dialecto).
# Con sa.Enum genérico el kwarg se absorbe en silencio (ni siquiera queda como atributo) y
# create_table() termina intentando crear el tipo igual al armar la columna 'status' —
# duplicado, porque ya lo creamos a mano abajo con SQL crudo (necesario porque el checkfirst
# de .create() tampoco es confiable acá: ver detalle en el próximo párrafo).
CONTACT_STATUS_ENUM = postgresql.ENUM('pending', 'resolved', name='contactrequeststatus', create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    # El tipo se crea con SQL crudo (DO $$ ... EXCEPTION), no con Enum.create(checkfirst=True):
    # ese checkfirst no es confiable con SQLAlchemy 2.x + asyncpg bajo Alembic async (el
    # chequeo puede no ver un tipo recién creado en la misma transacción). Postgres no soporta
    # "CREATE TYPE ... IF NOT EXISTS", así que DO $$ ... EXCEPTION WHEN duplicate_object es el
    # patrón estándar para hacerlo idempotente.
    bind.exec_driver_sql("""
        DO $$ BEGIN
            CREATE TYPE contactrequeststatus AS ENUM ('pending', 'resolved');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    if not sa.inspect(bind).has_table('human_contact_requests'):
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
    existing_indexes = {ix['name'] for ix in sa.inspect(bind).get_indexes('human_contact_requests')}
    if 'ix_human_contact_requests_chatbot_id' not in existing_indexes:
        op.create_index('ix_human_contact_requests_chatbot_id', 'human_contact_requests', ['chatbot_id'])
    if 'ix_human_contact_requests_status' not in existing_indexes:
        op.create_index('ix_human_contact_requests_status', 'human_contact_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_human_contact_requests_status', table_name='human_contact_requests')
    op.drop_index('ix_human_contact_requests_chatbot_id', table_name='human_contact_requests')
    op.drop_table('human_contact_requests')
    op.get_bind().exec_driver_sql("DROP TYPE IF EXISTS contactrequeststatus")
