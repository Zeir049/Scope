from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ShareLink


class ShareRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_active_by_project(self, project_id: uuid.UUID) -> ShareLink | None:
        res = await self.s.execute(
            select(ShareLink).where(
                ShareLink.project_id == project_id, ShareLink.revoked.is_(False)
            )
        )
        return res.scalars().first()

    async def list_by_project(self, project_id: uuid.UUID) -> list[ShareLink]:
        res = await self.s.execute(
            select(ShareLink)
            .where(ShareLink.project_id == project_id)
            .order_by(ShareLink.created_at.desc())
        )
        return list(res.scalars().all())

    async def get_by_id(self, link_id: uuid.UUID) -> ShareLink | None:
        return await self.s.get(ShareLink, link_id)

    async def get_by_token(self, token: str) -> ShareLink | None:
        res = await self.s.execute(select(ShareLink).where(ShareLink.token == token))
        return res.scalar_one_or_none()

    async def create(self, project_id: uuid.UUID, token: str) -> ShareLink:
        link = ShareLink(project_id=project_id, token=token)
        self.s.add(link)
        await self.s.flush()
        return link
