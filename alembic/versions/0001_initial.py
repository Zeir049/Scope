"""initial schema — users, projects, chapters, analysis, canon_*

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
NOW = sa.text("now()")


def _canon_version_cols() -> list[sa.Column]:
    """모든 canon_* 테이블 공통 버전 컬럼 (append-only, spec 4장)."""
    return [
        sa.Column("source_chapter", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by", UUID, nullable=True),
        sa.Column("superseded_at_chapter", sa.Integer(), nullable=True),
        sa.Column("entity_key", sa.String(), nullable=False),
    ]


def _project_fk_col() -> sa.Column:
    return sa.Column(
        "project_id",
        UUID,
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "projects",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "owner_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    op.create_table(
        "chapters",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "project_id",
            UUID,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("raw_text", sa.String(), nullable=True),
        sa.Column("raw_path", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
        sa.UniqueConstraint("project_id", "chapter_no"),
    )
    op.create_index("ix_chapters_project_id", "chapters", ["project_id"])

    op.create_table(
        "analysis_results",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "chapter_id",
            UUID,
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("highlighted", JSONB, nullable=True),
        sa.Column("raw_output", JSONB, nullable=True),
        sa.Column("canon_delta", JSONB, nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )
    op.create_index(
        "ix_analysis_results_chapter_id", "analysis_results", ["chapter_id"]
    )

    op.create_table(
        "contradictions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "chapter_id",
            UUID,
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span", JSONB, nullable=True),
        sa.Column("conflict_ref", JSONB, nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("explanation", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_contradictions_chapter_id", "contradictions", ["chapter_id"]
    )

    # ── 캐논 7테이블 ──────────────────────────────────────
    op.create_table(
        "canon_worldview",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("item", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_worldview_project_id", "canon_worldview", ["project_id"]
    )

    op.create_table(
        "canon_characters",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("group_name", sa.String(), nullable=True),
        sa.Column("attrs", JSONB, nullable=True),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_characters_project_id", "canon_characters", ["project_id"]
    )

    op.create_table(
        "canon_relations",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("from_char", sa.String(), nullable=False),
        sa.Column("to_char", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=True),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_relations_project_id", "canon_relations", ["project_id"]
    )

    op.create_table(
        "canon_timeline",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("scene_label", sa.String(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_value", sa.String(), nullable=True),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_timeline_project_id", "canon_timeline", ["project_id"]
    )

    op.create_table(
        "canon_spaces",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("scene_label", sa.String(), nullable=True),
        sa.Column("place", sa.String(), nullable=True),
        sa.Column("attrs", JSONB, nullable=True),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_spaces_project_id", "canon_spaces", ["project_id"]
    )

    op.create_table(
        "canon_events",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_events_project_id", "canon_events", ["project_id"]
    )

    op.create_table(
        "canon_foreshadowing",
        sa.Column("id", UUID, primary_key=True),
        _project_fk_col(),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("parent_key", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=True),
        *_canon_version_cols(),
    )
    op.create_index(
        "ix_canon_foreshadowing_project_id", "canon_foreshadowing", ["project_id"]
    )


def downgrade() -> None:
    for tbl in [
        "canon_foreshadowing",
        "canon_events",
        "canon_spaces",
        "canon_timeline",
        "canon_relations",
        "canon_characters",
        "canon_worldview",
        "contradictions",
        "analysis_results",
        "chapters",
        "projects",
        "users",
    ]:
        op.drop_table(tbl)
