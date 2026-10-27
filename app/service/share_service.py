"""공유 링크 비즈니스 로직. (ENABLE_SHARING)"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.security import generate_token
from app.models import ShareLink, User
from app.repository.chapter_repo import ChapterRepository
from app.repository.project_repo import ProjectRepository
from app.repository.share_repo import ShareRepository
from app.schemas.chapter import ChapterOut
from app.schemas.project import ProjectOut
from app.schemas.share import ShareLinkOut, SharedProjectOut
from app.service.ownership import assert_owned

logger = logging.getLogger(__name__)


class ShareService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.repo = ShareRepository(session)
        self.projects = ProjectRepository(session)
        self.chapters = ChapterRepository(session)

    def _to_out(self, link: ShareLink) -> ShareLinkOut:
        return ShareLinkOut(
            id=link.id,
            token=link.token,
            url=f"{settings.public_base_url}/shared/{link.token}",
            revoked=link.revoked,
            created_at=link.created_at,
        )

    async def create_link(self, user: User, project_id: uuid.UUID) -> ShareLinkOut:
        assert_owned(await self.projects.get_by_id(project_id), user)
        # 활성 링크가 있으면 재사용(중복 난발 방지)
        existing = await self.repo.get_active_by_project(project_id)
        if existing:
            return self._to_out(existing)
        link = await self.repo.create(project_id, generate_token())
        await self.s.commit()
        logger.info("share link created: project=%s", project_id)
        return self._to_out(link)

    async def list_links(self, user: User, project_id: uuid.UUID) -> list[ShareLinkOut]:
        assert_owned(await self.projects.get_by_id(project_id), user)
        return [self._to_out(link) for link in await self.repo.list_by_project(project_id)]

    async def revoke(self, user: User, link_id: uuid.UUID) -> None:
        link = await self.repo.get_by_id(link_id)
        if link is None:
            raise NotFoundError("공유 링크를 찾을 수 없습니다.")
        assert_owned(await self.projects.get_by_id(link.project_id), user)
        link.revoked = True
        await self.s.commit()

    async def get_public(self, token: str) -> SharedProjectOut:
        """인증 없이 토큰으로 보는 읽기전용 뷰."""
        link = await self.repo.get_by_token(token)
        if link is None or link.revoked:
            raise NotFoundError("유효하지 않은 공유 링크입니다.")
        project = await self.projects.get_by_id(link.project_id)
        if project is None:
            raise NotFoundError("프로젝트를 찾을 수 없습니다.")
        chapters = await self.chapters.list_by_project(project.id)
        return SharedProjectOut(
            project=ProjectOut.model_validate(project),
            chapters=[ChapterOut.model_validate(c) for c in chapters],
        )
