from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalysisResult, Chapter, ChapterStatus, Project

# (chapter, project_name, progress)
ActiveChapterRow = tuple[Chapter, str, int | None]


class ChapterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list_by_project(self, project_id: uuid.UUID) -> list[Chapter]:
        res = await self.s.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_no.asc())
        )
        return list(res.scalars().all())

    async def get(self, project_id: uuid.UUID, chapter_no: int) -> Chapter | None:
        res = await self.s.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.chapter_no == chapter_no,
            )
        )
        return res.scalar_one_or_none()

    async def create(
        self,
        project_id: uuid.UUID,
        chapter_no: int,
        title: str | None,
        raw_text: str | None,
        raw_path: str | None,
        kind: str = "narrative",
        content_hash: str | None = None,
    ) -> Chapter:
        chapter = Chapter(
            project_id=project_id,
            chapter_no=chapter_no,
            title=title,
            raw_text=raw_text,
            raw_path=raw_path,
            kind=kind,
            content_hash=content_hash,
            status=ChapterStatus.uploaded.value,
        )
        self.s.add(chapter)
        await self.s.flush()
        return chapter

    async def list_active_for_owner(
        self, owner_id: uuid.UUID, statuses: list[str]
    ) -> list[ActiveChapterRow]:
        """소유자의 모든 프로젝트에서 status 가 statuses 인 회차 — 프로젝트 조인 한 번.

        progress 는 그 회차의 최신 analysis_results.progress(상관 서브쿼리, N+1 없음).
        """
        progress = (
            select(AnalysisResult.progress)
            .where(AnalysisResult.chapter_id == Chapter.id)
            .order_by(AnalysisResult.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        res = await self.s.execute(
            select(Chapter, Project.name, progress)
            .join(Project, Project.id == Chapter.project_id)
            .where(Project.owner_id == owner_id, Chapter.status.in_(statuses))
            .order_by(Chapter.updated_at.asc())
        )
        return [(c, name, prog) for c, name, prog in res.all()]

    async def lock(self, chapter_id: uuid.UUID) -> Chapter | None:
        """회차 행을 잠그고(FOR UPDATE) 최신 값으로 다시 읽는다.

        저장(캐논 병합)이 동시에 두 번 들어와도(워커 자동 저장 + API save) 한쪽이
        커밋할 때까지 기다리게 해서 병합이 딱 한 번만 일어나게 한다(불변원칙 3).
        """
        res = await self.s.execute(
            select(Chapter)
            .where(Chapter.id == chapter_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return res.scalar_one_or_none()

    async def find_by_hash(
        self, project_id: uuid.UUID, content_hash: str
    ) -> Chapter | None:
        """같은 프로젝트에서 같은 원문 해시를 가진 회차 (가장 앞 회차 1건)."""
        res = await self.s.execute(
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.content_hash == content_hash,
            )
            .order_by(Chapter.chapter_no.asc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def delete(self, chapter: Chapter) -> None:
        """회차 삭제. analysis_results/contradictions 는 FK ON DELETE CASCADE."""
        await self.s.delete(chapter)
        await self.s.flush()
