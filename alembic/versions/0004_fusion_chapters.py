"""fusion 1단계: 회차 종류/수정시각/내용 해시 + 모순 판정 상태

- chapters.kind          narrative | rules (기본 narrative)
- chapters.updated_at    기존 행은 created_at 으로 채운다
- chapters.content_hash  파싱된 raw_text 의 sha256 hex — 같은 프로젝트 중복 업로드 판단(D3)
                         + 인덱스 (project_id, content_hash). 기존 행은 raw_text 로 계산.
- contradictions.status  pending | confirmed | dismissed (작가의 ✓/✕ 판정)

Revision ID: 0004_fusion_chapters
Revises: 0003_visual_json
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_fusion_chapters"
down_revision: Union[str, None] = "0003_visual_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chapters",
        sa.Column("kind", sa.String(), nullable=False, server_default="narrative"),
    )

    # 기존 행을 created_at 으로 채운 뒤 NOT NULL 로 조인다.
    op.add_column(
        "chapters",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("UPDATE chapters SET updated_at = COALESCE(created_at, now())")
    op.alter_column("chapters", "updated_at", nullable=False)

    # 해시는 앱(hashlib.sha256(text.encode('utf-8')).hexdigest())과 같은 값이 되도록 UTF-8 바이트로 계산.
    op.add_column("chapters", sa.Column("content_hash", sa.String(64), nullable=True))
    op.execute(
        """
        UPDATE chapters
        SET content_hash = encode(sha256(convert_to(raw_text, 'UTF8')), 'hex')
        WHERE raw_text IS NOT NULL AND raw_text <> ''
        """
    )
    op.create_index(
        "ix_chapters_project_id_content_hash", "chapters", ["project_id", "content_hash"]
    )

    op.add_column(
        "contradictions",
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
    )


def downgrade() -> None:
    op.drop_column("contradictions", "status")
    op.drop_index("ix_chapters_project_id_content_hash", table_name="chapters")
    op.drop_column("chapters", "content_hash")
    op.drop_column("chapters", "updated_at")
    op.drop_column("chapters", "kind")
