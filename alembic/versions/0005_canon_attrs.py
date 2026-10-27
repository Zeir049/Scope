"""캐논 attrs — 세계관·관계·시간·사건 테이블에도 attrs JSONB 추가

LLM 추출 결과(prompt_result_1 포맷)의 certainty·source_text, 사건의
summary/cause/result/참여 인물, 관계의 sentiment/description, 시간의 description 을
캐논이 버리지 않도록 인물·공간에만 있던 attrs 를 나머지 4개 테이블에도 둔다.
(복선은 원본 포맷에 없으므로 그대로.)

nullable 이라 기존 행은 NULL — 다음 저장에서 새 버전으로 채워진다.

Revision ID: 0005_canon_attrs
Revises: 0004_fusion_chapters
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_canon_attrs"
down_revision: Union[str, None] = "0004_fusion_chapters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("canon_worldview", "canon_relations", "canon_timeline", "canon_events")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("attrs", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "attrs")
