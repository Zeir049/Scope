from __future__ import annotations

import enum
import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class AnalysisResult(Base, TimestampMixin):
    """회차별 분석 결과(저장 전/후 모두 보관)."""

    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    highlighted: Mapped[dict] = mapped_column(JSONB, nullable=True)  # 본문+하이라이트
    raw_output: Mapped[dict] = mapped_column(JSONB, nullable=True)   # 실패 기록 {error, stage}
    # LLM 원본 시각화 JSON(prompt_result_1 포맷) — GET .../visual 로 내려간다
    visual_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    # canon_delta 를 보관해 save 시 병합에 사용 (파이프라인 → 몸통 계약)
    canon_delta: Mapped[dict] = mapped_column(JSONB, nullable=True)
    progress: Mapped[int] = mapped_column(default=0)  # 폴링용 진행률 0~100


class ContradictionStatus(str, enum.Enum):
    """작가의 모순 판정 (✓/✕). 회차 진행 상태(chapters.status)와는 별개."""

    pending = "pending"
    confirmed = "confirmed"
    dismissed = "dismissed"


class Contradiction(Base):
    """검출된 모순 (사용자 표시용)."""

    __tablename__ = "contradictions"

    id: Mapped[uuid.UUID] = uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    span: Mapped[dict] = mapped_column(JSONB, nullable=True)          # 신규 회차 내 위치
    conflict_ref: Mapped[dict] = mapped_column(JSONB, nullable=True)  # 충돌 기존 캐논/회차
    # setting|character|timeline|space|event|foreshadow
    type: Mapped[str] = mapped_column(String, nullable=False)
    explanation: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=ContradictionStatus.pending.value,
        server_default=ContradictionStatus.pending.value,
    )
