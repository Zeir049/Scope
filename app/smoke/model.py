# ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 삭제. 삭제법은 app/smoke/README.md 참조
"""스모크 테스트 결과 ORM 모델.

기존 app.models.base.Base 를 재사용하되, 이 테이블은 Alembic 체인에 넣지 않는다
(생성은 app/smoke/table.ensure_smoke_table, 삭제는 수동 DROP TABLE).
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class SmokeCheck(Base, TimestampMixin):
    """한 번의 스모크 왕복 기록: 이 사용자가 가짜 LLM으로부터 응답('ok')을 받았는지."""

    __tablename__ = "smoke_checks"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    # 프로젝트 없이도 왕복 가능하도록 nullable. (FK 없이 느슨하게 — 격리 목적)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    # created_at 은 TimestampMixin 이 제공 (timestamptz, server_default now()).
