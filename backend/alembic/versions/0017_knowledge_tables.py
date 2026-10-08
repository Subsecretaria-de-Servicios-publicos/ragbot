"""knowledge_tables

Base de conocimiento estructurada que arma el admin (columnas y filas a elección). Cada fila
se indexa como un chunk más del mismo pipeline de RAG que los documentos (Document "virtual"
por tabla, sin archivo real — documents.source la distingue de un PDF subido).

Revision ID: 0017_knowledge_tables
Revises: 0016_bot_forms
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0017_knowledge_tables'
down_revision: Union[str, None] = '0016_bot_forms'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FIELD_TYPE_ENUM = postgresql.ENUM('text', 'number', 'email', 'date', name='knowledgefieldtype', create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("""
        DO $$ BEGIN
            CREATE TYPE knowledgefieldtype AS ENUM ('text', 'number', 'email', 'date');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    inspector = sa.inspect(bind)

    existing_cols = {c['name'] for c in inspector.get_columns('documents')}
    if 'source' not in existing_cols:
        op.add_column('documents', sa.Column('source', sa.String(length=20), nullable=False, server_default='upload'))

    if not inspector.has_table('knowledge_tables'):
        op.create_table(
            'knowledge_tables',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('chatbot_id', sa.String(length=36), sa.ForeignKey('chatbots.id', ondelete='CASCADE'), nullable=False),
            sa.Column('document_id', sa.String(length=36), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.String(length=36), nullable=True),
        )
        op.create_index('ix_knowledge_tables_chatbot_id', 'knowledge_tables', ['chatbot_id'])

    if not inspector.has_table('knowledge_fields'):
        op.create_table(
            'knowledge_fields',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('table_id', sa.String(length=36), sa.ForeignKey('knowledge_tables.id', ondelete='CASCADE'), nullable=False),
            sa.Column('key', sa.String(length=100), nullable=False),
            sa.Column('label', sa.String(length=200), nullable=False),
            sa.Column('field_type', FIELD_TYPE_ENUM, nullable=False),
            sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        )
        op.create_index('ix_knowledge_fields_table_id', 'knowledge_fields', ['table_id'])

    if not inspector.has_table('knowledge_rows'):
        op.create_table(
            'knowledge_rows',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('table_id', sa.String(length=36), sa.ForeignKey('knowledge_tables.id', ondelete='CASCADE'), nullable=False),
            sa.Column('data', postgresql.JSONB(), nullable=False, server_default='{}'),
            sa.Column('chunk_id', sa.String(length=36), sa.ForeignKey('document_chunks.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.String(length=36), nullable=True),
        )
        op.create_index('ix_knowledge_rows_table_id', 'knowledge_rows', ['table_id'])


def downgrade() -> None:
    op.drop_table('knowledge_rows')
    op.drop_table('knowledge_fields')
    op.drop_table('knowledge_tables')
    op.drop_column('documents', 'source')
    op.get_bind().exec_driver_sql("DROP TYPE IF EXISTS knowledgefieldtype")
