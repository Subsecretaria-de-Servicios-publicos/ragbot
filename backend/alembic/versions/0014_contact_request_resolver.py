"""contact_request_resolver

Quién marcó una consulta ("hablar con una persona") como resuelta y cuándo.

Revision ID: 0014_contact_resolver
Revises: 0013_conv_chatbot_cascade
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0014_contact_resolver'
down_revision: Union[str, None] = '0013_conv_chatbot_cascade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('human_contact_requests',
                   sa.Column('resolved_by', sa.String(length=36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.add_column('human_contact_requests', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('human_contact_requests', 'resolved_at')
    op.drop_column('human_contact_requests', 'resolved_by')
