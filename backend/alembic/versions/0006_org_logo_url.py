"""org_logo_url

Revision ID: 0006_org_logo_url
Revises: 0005_chatbot_assignments
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0006_org_logo_url'
down_revision: Union[str, None] = '0005_chatbot_assignments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chatbots', sa.Column('org_logo_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('chatbots', 'org_logo_url')
