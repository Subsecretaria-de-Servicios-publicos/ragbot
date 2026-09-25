"""chatbot_assignments

Revision ID: 0005_chatbot_assignments
Revises: 0004_ai_provider_configs
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005_chatbot_assignments'
down_revision: Union[str, None] = '0004_ai_provider_configs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chatbot_assignments',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('chatbot_id', sa.String(length=36), sa.ForeignKey('chatbots.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('chatbot_id', 'user_id', name='uq_chatbot_assignment'),
    )
    op.create_index('ix_chatbot_assignments_user_id', 'chatbot_assignments', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_chatbot_assignments_user_id', table_name='chatbot_assignments')
    op.drop_table('chatbot_assignments')
