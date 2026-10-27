from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list_for_user(
        self, user_id: uuid.UUID, unread_only: bool = False
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc())
        res = await self.s.execute(stmt)
        return list(res.scalars().all())

    async def get(self, notif_id: uuid.UUID) -> Notification | None:
        return await self.s.get(Notification, notif_id)

    async def create(
        self, user_id: uuid.UUID, type_: str, message: str
    ) -> Notification:
        notif = Notification(user_id=user_id, type=type_, message=message)
        self.s.add(notif)
        await self.s.flush()
        return notif

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        rows = await self.list_for_user(user_id, unread_only=True)
        for r in rows:
            r.is_read = True
