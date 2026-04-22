"""Initial migration — todas las tablas con pgvector

Revision ID: 0001_initial
Revises: 
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Habilitar extensión pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Users
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('username', sa.String(100), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255)),
        sa.Column('role', sa.Enum('superadmin', 'admin', 'operator', 'viewer', name='userrole'), default='viewer'),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_login', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Chatbots
    op.create_table(
        'chatbots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('slug', sa.String(200), unique=True, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_public', sa.Boolean, default=False),
        sa.Column('ai_provider', sa.Enum('openai', 'anthropic', 'google', 'ollama', name='aiprovider'), default='openai'),
        sa.Column('ai_model', sa.String(100), default='gpt-4o-mini'),
        sa.Column('temperature', sa.Float, default=0.7),
        sa.Column('max_tokens', sa.Integer, default=1000),
        sa.Column('system_prompt', sa.Text),
        sa.Column('welcome_message', sa.Text, default='¡Hola! ¿En qué puedo ayudarte?'),
        sa.Column('bot_name', sa.String(100), default='Asistente'),
        sa.Column('bot_avatar_url', sa.String(500)),
        sa.Column('widget_config', JSONB),
        sa.Column('top_k', sa.Integer, default=5),
        sa.Column('similarity_threshold', sa.Float, default=0.7),
        sa.Column('total_conversations', sa.Integer, default=0),
        sa.Column('total_messages', sa.Integer, default=0),
        sa.Column('total_tokens_used', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Documents
    op.create_table(
        'documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chatbot_id', sa.String(36), sa.ForeignKey('chatbots.id', ondelete='CASCADE')),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('file_path', sa.String(1000), nullable=False),
        sa.Column('file_size', sa.Integer, default=0),
        sa.Column('mime_type', sa.String(100)),
        sa.Column('status', sa.Enum('pending', 'processing', 'ready', 'error', name='documentstatus'), default='pending'),
        sa.Column('error_message', sa.Text),
        sa.Column('chunk_count', sa.Integer, default=0),
        sa.Column('page_count', sa.Integer, default=0),
        sa.Column('uploaded_by', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('processed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Document Chunks (con vector)
    op.create_table(
        'document_chunks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id', ondelete='CASCADE')),
        sa.Column('chatbot_id', sa.String(36), sa.ForeignKey('chatbots.id', ondelete='CASCADE')),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('chunk_index', sa.Integer, default=0),
        sa.Column('page_number', sa.Integer),
        sa.Column('metadata', JSONB),
        sa.Column('embedding', Vector(1536)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Índice HNSW para búsqueda rápida de vectores
    op.execute("""
        CREATE INDEX ix_chunks_embedding_hnsw ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.create_index('ix_chunks_chatbot_id', 'document_chunks', ['chatbot_id'])

    # Conversations
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chatbot_id', sa.String(36), sa.ForeignKey('chatbots.id')),
        sa.Column('session_id', sa.String(100), nullable=False),
        sa.Column('user_identifier', sa.String(255)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.String(500)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('total_messages', sa.Integer, default=0),
        sa.Column('total_tokens', sa.Integer, default=0),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_activity', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Messages
    op.create_table(
        'messages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id', ondelete='CASCADE')),
        sa.Column('role', sa.Enum('user', 'assistant', 'system', name='messagerole'), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('model_used', sa.String(100)),
        sa.Column('provider_used', sa.String(50)),
        sa.Column('prompt_tokens', sa.Integer, default=0),
        sa.Column('completion_tokens', sa.Integer, default=0),
        sa.Column('total_tokens', sa.Integer, default=0),
        sa.Column('latency_ms', sa.Integer),
        sa.Column('retrieved_chunks', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # API Keys
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chatbot_id', sa.String(36), sa.ForeignKey('chatbots.id', ondelete='CASCADE')),
        sa.Column('key_hash', sa.String(255), unique=True),
        sa.Column('name', sa.String(200), default='Default'),
        sa.Column('allowed_origins', JSONB),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_used', sa.DateTime(timezone=True)),
        sa.Column('requests_count', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('api_keys')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('document_chunks')
    op.drop_table('documents')
    op.drop_table('chatbots')
    op.drop_table('users')
    op.execute("DROP TYPE IF EXISTS userrole, aiprovider, documentstatus, messagerole")
    op.execute("DROP EXTENSION IF EXISTS vector")
