from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk


class ChapterStatus(str, enum.Enum):
    """회차 상태 머신 (spec 3장). status가 단일 진실 원천.

    2단계 분리: uploaded → extracting → extracted → reviewing → reviewed → saved.
    어느 단계든 실패하면 failed(+ 실패 단계/사유는 analysis_results.raw_output에 기록).
    status는 자유 문자열 컬럼이라 상태값 추가에 DB 마이그레이션이 필요 없다.
    """

    uploaded = "uploaded"
    extracting = "extracting"  # 1차 추출 진행 중
    extracted = "extracted"    # 추출 완료(canon_delta) → 사용자 검토 대기
    reviewing = "reviewing"    # 2차 검수 진행 중
    reviewed = "reviewed"      # 검수 완료(contradictions) → 저장 대기
    saved = "saved"
    failed = "failed"


class ChapterKind(str, enum.Enum):
    """회차 종류. narrative = 서사 원고, rules = 작가가 쓴 설정/규칙 문서."""

    narrative = "narrative"
    rules = "rules"


class Chapter(Base, TimestampMixin):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("project_id", "chapter_no"),
        # 같은 프로젝트 안 중복 업로드 판단용 (D3, 마이그레이션 0004)
        Index("ix_chapters_project_id_content_hash", "project_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)  # 업로드 원문
    raw_path: Mapped[str | None] = mapped_column(String, nullable=True)  # 파일 저장 경로
    kind: Mapped[str] = mapped_column(
        String, nullable=False, default=ChapterKind.narrative.value,
        server_default=ChapterKind.narrative.value,
    )
    # 파싱된 raw_text 의 sha256 hex. 원문이 바뀔 때마다 서비스가 갱신한다.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # status는 문자열로 저장(상태머신). 기본 uploaded.
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=ChapterStatus.uploaded.value
    )

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    project: Mapped["Project"] = relationship(back_populates="chapters")  # noqa: F821
