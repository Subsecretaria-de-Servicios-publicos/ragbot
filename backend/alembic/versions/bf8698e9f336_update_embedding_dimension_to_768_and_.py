"""update_embedding_dimension_to_768_and_metadata_fix

Revision ID: bf8698e9f336
Revises: 0001_initial
Create Date: 2026-04-22 22:23:59.769902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'bf8698e9f336'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename metadata to chunk_metadata
    op.alter_column('document_chunks', 'metadata', new_column_name='chunk_metadata')

    # 2. Update embedding dimension
    # Drop index first
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")

    # To change the dimension safely when data exists, we have a few options:
    # a) Set existing embeddings to NULL and then change type.
    # b) Drop and recreate the column.
    # Since existing embeddings (1536) are incompatible with 768, we must clear them.

    op.execute("UPDATE document_chunks SET embedding = NULL")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768)")

    # Re-create index
    op.execute("""
        CREATE INDEX ix_chunks_embedding_hnsw ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("UPDATE document_chunks SET embedding = NULL")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536)")
    op.execute("""
        CREATE INDEX ix_chunks_embedding_hnsw ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.alter_column('document_chunks', 'chunk_metadata', new_column_name='metadata')
