"""conversations_chatbot_cascade

Bug preexistente: conversations.chatbot_id nunca tuvo ON DELETE CASCADE (a diferencia de
documents/chatbot_assignments/document_chunks, que sí lo tienen desde 0001_initial). Borrar un
chatbot que ya tiene conversaciones fallaba con un 500 (NotNullViolationError), porque el ORM
intenta poner NULL en esa FK al borrar el padre y la columna es NOT NULL. Se detectó armando
una prueba de otra funcionalidad (bot_files) que de paso ejercitaba delete_chatbot con
conversaciones ya creadas.

Revision ID: 0013_conv_chatbot_cascade
Revises: 0012_bot_files
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0013_conv_chatbot_cascade'
down_revision: Union[str, None] = '0012_bot_files'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _find_fk_name(conn, table: str, column: str, ref_table: str) -> str | None:
    insp = sa.inspect(conn)
    for fk in insp.get_foreign_keys(table):
        if fk.get("referred_table") == ref_table and column in (fk.get("constrained_columns") or []):
            return fk.get("name")
    return None


def upgrade() -> None:
    conn = op.get_bind()
    fk_name = _find_fk_name(conn, "conversations", "chatbot_id", "chatbots")
    if fk_name:
        op.drop_constraint(fk_name, "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_chatbot_id_fkey", "conversations", "chatbots",
        ["chatbot_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    conn = op.get_bind()
    fk_name = _find_fk_name(conn, "conversations", "chatbot_id", "chatbots")
    if fk_name:
        op.drop_constraint(fk_name, "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_chatbot_id_fkey", "conversations", "chatbots",
        ["chatbot_id"], ["id"],
    )
