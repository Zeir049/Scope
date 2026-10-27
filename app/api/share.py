"""공유 라우터. (ENABLE_SHARING)

/shared/{token} 만 공개(인증 불필요), 나머지는 소유자 인증 필요.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.schemas.share import ShareLinkOut, SharedProjectOut
from app.service.share_service import ShareService

router = APIRouter(tags=["sharing"])


@router.post("/projects/{project_id}/share", response_model=ShareLinkOut, status_code=201)
async def create_share(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ShareLinkOut:
    return await ShareService(session).create_link(user, project_id)


@router.get("/projects/{project_id}/shares", response_model=list[ShareLinkOut])
async def list_shares(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ShareLinkOut]:
    return await ShareService(session).list_links(user, project_id)


@router.delete("/shares/{link_id}", status_code=204)
async def revoke_share(
    link_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await ShareService(session).revoke(user, link_id)
    return Response(status_code=204)


@router.get("/shared/{token}", response_model=SharedProjectOut, tags=["sharing"])
async def view_shared(
    token: str, session: AsyncSession = Depends(get_session)
) -> SharedProjectOut:
    # 공개 엔드포인트: 인증 불필요(토큰만으로 읽기전용 조회)
    return await ShareService(session).get_public(token)
