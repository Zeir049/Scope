"""알림 비즈니스 로직. (ENABLE_NOTIFICATIONS)"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import User
from app.repository.notification_repo import NotificationRepository
from app.schemas.notification import NotificationOut

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.repo = NotificationRepository(session)

    async def list(self, user: User, unread_only: bool = False) -> list[NotificationOut]:
        rows = await self.repo.list_for_user(user.id, unread_only=unread_only)
        return [NotificationOut.model_validate(n) for n in rows]

    async def mark_read(self, user: User, notif_id: uuid.UUID) -> None:
        notif = await self.repo.get(notif_id)
        if notif is None:
            raise NotFoundError("알림을 찾을 수 없습니다.")
        if notif.user_id != user.id:
            raise PermissionDeniedError("접근 권한이 없습니다.")
        notif.is_read = True
        await self.s.commit()

    async def mark_all_read(self, user: User) -> None:
        await self.repo.mark_all_read(user.id)
        await self.s.commit()
