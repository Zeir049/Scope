"""캐논 테이블 공통 DB 접근. append-only 버전 관리의 SQL은 여기에만.

7개 canon_* 테이블이 동일한 버전 컬럼을 공유하므로 모델 클래스를 인자로 받아
제네릭하게 처리한다.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class CanonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_current(
        self, model: type[Base], project_id: uuid.UUID, entity_key: str
    ) -> Any | None:
        """같은 항목(entity_key)의 현재 유효 버전 1건."""
        res = await self.s.execute(
            select(model).where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.entity_key == entity_key,  # type: ignore[attr-defined]
                model.is_current.is_(True),  # type: ignore[attr-defined]
            )
        )
        return res.scalar_one_or_none()

    async def list_current(
        self, model: type[Base], project_id: uuid.UUID
    ) -> list[Any]:
        """현재 캐논(is_current=true) 전체."""
        res = await self.s.execute(
            select(model).where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.is_current.is_(True),  # type: ignore[attr-defined]
            )
        )
        return list(res.scalars().all())

    async def list_at_chapter(
        self, model: type[Base], project_id: uuid.UUID, chapter_no: int
    ) -> list[Any]:
        """N화 시점에 유효했던 버전들.

        source_chapter <= N AND (superseded_at_chapter IS NULL OR superseded_at_chapter > N).
        철회된 행은 superseded_at_chapter = source_chapter 라 자기 회차부터 빠지고,
        복원된 행은 superseded_at_chapter 가 NULL 로 돌아가 다시 잡힌다.
        """
        res = await self.s.execute(
            select(model).where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.source_chapter <= chapter_no,  # type: ignore[attr-defined]
                or_(
                    model.superseded_at_chapter.is_(None),  # type: ignore[attr-defined]
                    model.superseded_at_chapter > chapter_no,  # type: ignore[attr-defined]
                ),
            )
        )
        return list(res.scalars().all())

    async def list_by_source(
        self, model: type[Base], project_id: uuid.UUID, chapter_no: int
    ) -> list[Any]:
        """N화가 캐논에 넣은 행 전부 — 이후 회차에서 대체·철회된 버전도 포함(is_current 무관).

        회차별 시각화용. 같은 entity_key 가 여러 버전(같은 회차 재저장)일 수 있어 version 순.
        """
        res = await self.s.execute(
            select(model)
            .where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.source_chapter == chapter_no,  # type: ignore[attr-defined]
            )
            .order_by(model.version)  # type: ignore[attr-defined]
        )
        return list(res.scalars().all())

    async def has_contribution(
        self, models: list[type[Base]], project_id: uuid.UUID, source_chapter: int
    ) -> bool:
        """여러 캐논 테이블 중 하나라도 source_chapter 출처 행이 있으면 True — EXISTS 를 OR 로 한 번에."""
        conds = [
            exists().where(
                m.project_id == project_id,  # type: ignore[attr-defined]
                m.source_chapter == source_chapter,  # type: ignore[attr-defined]
            )
            for m in models
        ]
        return bool(await self.s.scalar(select(or_(*conds))))

    async def list_current_by_source(
        self, model: type[Base], project_id: uuid.UUID, source_chapter: int
    ) -> list[Any]:
        """이 회차가 출처인 현재 버전들 — 재저장 시 철회 후보 탐색용."""
        res = await self.s.execute(
            select(model).where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.is_current.is_(True),  # type: ignore[attr-defined]
                model.source_chapter == source_chapter,  # type: ignore[attr-defined]
            )
        )
        return list(res.scalars().all())

    async def get_latest_excluding_source(
        self,
        model: type[Base],
        project_id: uuid.UUID,
        entity_key: str,
        source_chapter: int,
    ) -> Any | None:
        """다른 회차가 만든 가장 최신 버전 — 철회 시 복원 대상.

        같은 회차가 만든 버전들은 전부 '철회되는 기여'이므로 건너뛴다.
        """
        res = await self.s.execute(
            select(model)
            .where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.entity_key == entity_key,  # type: ignore[attr-defined]
                model.source_chapter != source_chapter,  # type: ignore[attr-defined]
            )
            .order_by(model.version.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def get_max_version(
        self, model: type[Base], project_id: uuid.UUID, entity_key: str
    ) -> int:
        """이 항목의 최대 버전(철회된 버전 포함). 없으면 0 — 재추가 시 이어 매김용."""
        res = await self.s.scalar(
            select(func.coalesce(func.max(model.version), 0)).where(  # type: ignore[attr-defined]
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.entity_key == entity_key,  # type: ignore[attr-defined]
            )
        )
        return int(res or 0)

    async def insert_version(
        self,
        model: type[Base],
        project_id: uuid.UUID,
        entity_key: str,
        content: dict,
        version: int,
        source_chapter: int,
    ) -> Any:
        """새 버전 행 INSERT (is_current=true)."""
        obj = model(
            project_id=project_id,
            entity_key=entity_key,
            source_chapter=source_chapter,
            version=version,
            is_current=True,
            **content,
        )
        self.s.add(obj)
        await self.s.flush()
        return obj
