"""캐논(누적 구조화 데이터). 파이프라인이 생성, 몸통은 저장/병합/조회만.

모든 테이블이 CanonVersionMixin(append-only 버전 컬럼)을 공유한다.
현재 캐논 조회: WHERE is_current = true
시점 캐논 조회: source_chapter <= N AND (superseded_at_chapter IS NULL OR > N)
회차 기여 조회: source_chapter = N (대체된 버전 포함)

attrs(JSONB): LLM 추출 원본의 부가 정보(certainty·source_text 등, transform.py 참고).
복선(canon_foreshadowing)은 원본 포맷에 없어 attrs 가 없다.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CanonVersionMixin, uuid_pk


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )


class CanonWorldview(Base, CanonVersionMixin):
    __tablename__ = "canon_worldview"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    item: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CanonCharacter(Base, CanonVersionMixin):
    __tablename__ = "canon_characters"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    group_name: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=True)


class CanonRelation(Base, CanonVersionMixin):
    __tablename__ = "canon_relations"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    # from/to 는 인물 entity_key 로 잇는다(노드 식별). graph 렌더링용.
    from_char: Mapped[str] = mapped_column(String, nullable=False)
    to_char: Mapped[str] = mapped_column(String, nullable=False)
    relation: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CanonTimeline(Base, CanonVersionMixin):
    __tablename__ = "canon_timeline"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    scene_label: Mapped[str | None] = mapped_column(String, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    time_value: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CanonSpace(Base, CanonVersionMixin):
    __tablename__ = "canon_spaces"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    scene_label: Mapped[str | None] = mapped_column(String, nullable=True)
    place: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=True)


class CanonEvent(Base, CanonVersionMixin):
    __tablename__ = "canon_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    label: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str | None] = mapped_column(String, nullable=True)  # 암시|궁지1|궁지2|절정
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    attrs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CanonForeshadowing(Base, CanonVersionMixin):
    __tablename__ = "canon_foreshadowing"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    label: Mapped[str] = mapped_column(String, nullable=False)
    # 트리 구성: parent_id 는 같은 테이블의 entity_key 를 가리킨다.
    parent_key: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)  # setup|payoff
