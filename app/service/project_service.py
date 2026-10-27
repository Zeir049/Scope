"""프로젝트 비즈니스 로직 + 소유권 검사 + 트랜잭션 경계."""
from __future__ import annotations

import logging
import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError

from app.models import Project, User
from app.repository.project_repo import ProjectRepository
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.service.ownership import assert_owned

logger = logging.getLogger(__name__)

PAGE_SIZE = 20  # 기본값. 화면(내 드라이브)은 6을 쓴다.
MAX_PAGE_SIZE = 50
AUTO_NAME_PREFIX = "Project_"


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.repo = ProjectRepository(session)

    @staticmethod
    def _out(project: Project, chapter_count: int, last_status: str | None) -> ProjectOut:
        out = ProjectOut.model_validate(project)
        out.chapter_count = chapter_count
        out.last_chapter_status = last_status
        return out

    async def _out_with_stats(self, project: Project) -> ProjectOut:
        return self._out(project, *await self.repo.get_chapter_stats(project.id))

    async def list_projects(
        self, user: User, page: int, q: str | None, page_size: int = PAGE_SIZE
    ) -> Page[ProjectOut]:
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise DomainError(f"page_size는 1~{MAX_PAGE_SIZE} 사이여야 합니다.")
        page = max(page, 1)
        rows, total = await self.repo.list_by_owner(
            owner_id=user.id, page=page, size=page_size, q=q
        )
        total_pages = max(math.ceil(total / page_size), 1)
        return Page[ProjectOut](
            items=[self._out(p, cnt, last) for p, cnt, last in rows],
            page=page,
            total_pages=total_pages,
            total_count=total,
        )

    async def create(self, user: User, body: ProjectCreate) -> ProjectOut:
        name = (body.name or "").strip()
        if not name:
            n = await self.repo.max_auto_name_number(user.id) + 1
            name = f"{AUTO_NAME_PREFIX}{n}"
        project = await self.repo.create(
            owner_id=user.id, name=name, author=body.author or user.name
        )
        await self.s.commit()
        logger.info("project created: %s by %s", project.id, user.id)
        return self._out(project, 0, None)

    async def get(self, user: User, project_id: uuid.UUID) -> ProjectOut:
        project = assert_owned(await self.repo.get_by_id(project_id), user)
        return await self._out_with_stats(project)

    async def update(
        self, user: User, project_id: uuid.UUID, body: ProjectUpdate
    ) -> ProjectOut:
        project = assert_owned(await self.repo.get_by_id(project_id), user)
        # 보낸 필드만 반영(부분 수정)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        await self.s.commit()
        # updated_at(onupdate=server now())은 UPDATE 후 만료되므로 async 컨텍스트에서 재로딩
        await self.s.refresh(project)
        logger.info("project updated: %s fields=%s", project_id, list(body.model_dump(exclude_unset=True)))
        return await self._out_with_stats(project)

    async def set_thumbnail(
        self, user: User, project_id: uuid.UUID, url: str
    ) -> ProjectOut:
        project = assert_owned(await self.repo.get_by_id(project_id), user)
        project.thumbnail_url = url
        await self.s.commit()
        await self.s.refresh(project)
        return await self._out_with_stats(project)

    async def delete(self, user: User, project_id: uuid.UUID) -> None:
        project = assert_owned(await self.repo.get_by_id(project_id), user)
        await self.repo.delete(project)
        await self.s.commit()
        logger.info("project deleted: %s", project_id)

    async def get_owned(self, user: User, project_id: uuid.UUID) -> Project:
        """다른 서비스(회차 등)가 소유 프로젝트를 확보할 때 재사용."""
        return assert_owned(await self.repo.get_by_id(project_id), user)
