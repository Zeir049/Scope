"""알림 라우터. (ENABLE_NOTIFICATIONS)"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.schemas.notification import NotificationOut
from app.service.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationOut]:
    return await NotificationService(session).list(user, unread_only=unread_only)


@router.post("/read-all", status_code=204)
async def mark_all_read(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await NotificationService(session).mark_all_read(user)
    return Response(status_code=204)


@router.post("/{notif_id}/read", status_code=204)
async def mark_read(
    notif_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await NotificationService(session).mark_read(user, notif_id)
    return Response(status_code=204)
