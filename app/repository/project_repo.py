from __future__ import annotations

import uuid

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, array_agg
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, Project

# 자동 이름(Project_N) 패턴. 자릿수 상한은 int 캐스트 오버플로 방지.
_AUTO_NAME_PATTERN = r"^Project_(\d{1,9})$"

# (project, chapter_count, last_chapter_status)
ProjectRow = tuple[Project, int, str | None]


def _chapter_stats_subquery():
    """프로젝트별 회차 수 + 마지막(가장 큰 chapter_no) 회차 status — 집계 한 번."""
    return (
        select(
            Chapter.project_id.label("project_id"),
            func.count().label("chapter_count"),
            array_agg(
                aggregate_order_by(Chapter.status, Chapter.chapter_no.desc())
            )[1].label("last_chapter_status"),
        )
        .group_by(Chapter.project_id)
        .subquery()
    )


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return await self.s.get(Project, project_id)

    async def list_by_owner(
        self, owner_id: uuid.UUID, page: int, size: int, q: str | None
    ) -> tuple[list[ProjectRow], int]:
        """소유자 필터 + 검색(q) + 페이지네이션 + 회차 집계. (rows, total_count) 반환."""
        where = [Project.owner_id == owner_id]
        if q:
            where.append(Project.name.ilike(f"%{q}%"))

        total = await self.s.scalar(
            select(func.count()).select_from(Project).where(*where)
        )
        stats = _chapter_stats_subquery()
        res = await self.s.execute(
            select(
                Project,
                func.coalesce(stats.c.chapter_count, 0),
                stats.c.last_chapter_status,
            )
            .outerjoin(stats, stats.c.project_id == Project.id)
            .where(*where)
            .order_by(Project.updated_at.desc())
            .limit(size)
            .offset((page - 1) * size)
        )
        rows = [(p, int(cnt), last) for p, cnt, last in res.all()]
        return rows, int(total or 0)

    async def get_chapter_stats(self, project_id: uuid.UUID) -> tuple[int, str | None]:
        """단건 응답용 회차 집계 (chapter_count, last_chapter_status)."""
        stats = _chapter_stats_subquery()
        row = (
            await self.s.execute(
                select(stats.c.chapter_count, stats.c.last_chapter_status).where(
                    stats.c.project_id == project_id
                )
            )
        ).first()
        return (int(row[0]), row[1]) if row else (0, None)

    async def max_auto_name_number(self, owner_id: uuid.UUID) -> int:
        """이 사용자의 Project_<숫자> 이름 중 최대 숫자. 없으면 0."""
        n = await self.s.scalar(
            select(
                func.max(cast(func.substring(Project.name, _AUTO_NAME_PATTERN), Integer))
            ).where(
                Project.owner_id == owner_id,
                Project.name.regexp_match(_AUTO_NAME_PATTERN),
            )
        )
        return int(n or 0)

    async def touch(self, project_id: uuid.UUID) -> None:
        """updated_at 을 지금으로. 회차 변화는 프로젝트 행을 안 바꾸므로 onupdate 가 안 돈다."""
        await self.s.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(updated_at=func.now())
            .execution_options(synchronize_session=False)
        )

    async def create(
        self, owner_id: uuid.UUID, name: str, author: str | None = None
    ) -> Project:
        project = Project(owner_id=owner_id, name=name, author=author)
        self.s.add(project)
        await self.s.flush()
        return project

    async def delete(self, project: Project) -> None:
        await self.s.delete(project)
