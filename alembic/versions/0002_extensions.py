"""extensions: password reset, share, chat, notifications + canon partial unique index

Revision ID: 0002_extensions
Revises: 0001_initial
Create Date: 2026-06-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_extensions"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

CANON_TABLES = [
    "canon_worldview",
    "canon_characters",
    "canon_relations",
    "canon_timeline",
    "canon_spaces",
    "canon_events",
    "canon_foreshadowing",
]


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"])

    op.create_table(
        "share_links",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_share_links_project_id", "share_links", ["project_id"])
    op.create_index("ix_share_links_token", "share_links", ["token"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )
    op.create_index("ix_chat_sessions_project_id", "chat_sessions", ["project_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("session_id", UUID, sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    # 견고성: 항목(project_id, entity_key)당 is_current=true 행이 최대 1개임을 DB가 보장.
    for tbl in CANON_TABLES:
        op.create_index(
            f"uq_{tbl}_current",
            tbl,
            ["project_id", "entity_key"],
            unique=True,
            postgresql_where=sa.text("is_current"),
        )


def downgrade() -> None:
    for tbl in CANON_TABLES:
        op.drop_index(f"uq_{tbl}_current", table_name=tbl)
    for tbl in ["notifications", "chat_messages", "chat_sessions", "share_links", "password_reset_tokens"]:
        op.drop_table(tbl)
