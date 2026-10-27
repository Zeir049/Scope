from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class ShareLink(Base, TimestampMixin):
    """프로젝트 공개(읽기전용) 링크 토큰."""

    __tablename__ = "share_links"
    # DB 형태(마이그레이션)와 동일: 유니크 제약 + 일반 인덱스
    __table_args__ = (
        UniqueConstraint("token", name="share_links_token_key"),
        Index("ix_share_links_token", "token"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
