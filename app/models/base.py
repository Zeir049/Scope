"""ORM 베이스 + 공통 컬럼/믹스인."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    # DB(0001/0002)는 nullable. 값은 server_default 가 항상 채운다.
    created_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


class CanonVersionMixin:
    """캐논 테이블 공통 버전 컬럼 (append-only, spec 4장).

    덮어쓰지 않는다: 설정이 바뀌면 옛 행 is_current=false 로 두고
    새 행을 version+1, is_current=true 로 INSERT.
    """

    @declared_attr.directive
    def __table_args__(cls) -> tuple:
        # 항목(project_id, entity_key)당 is_current=true 행 최대 1개 (마이그레이션 0002와 동일)
        return (
            Index(
                f"uq_{cls.__tablename__}_current",
                "project_id",
                "entity_key",
                unique=True,
                postgresql_where=text("is_current"),
            ),
        )

    # 이 값이 들어온/변경된 회차
    source_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    # 같은 항목의 몇 번째 버전인가 (1,2,3…)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 현재 유효한 버전인가
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 이 버전을 대체한 새 버전의 id (없으면 NULL)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 몇 화에서 대체되었나
    superseded_at_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "같은 항목"을 잇는 논리 키 (예: 인물명, 설정 식별자)
    entity_key: Mapped[str] = mapped_column(String, nullable=False)
