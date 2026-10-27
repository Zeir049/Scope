"""캐논(자료정리 6탭) 라우터 (계약서 4장)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.schemas.canon import CanonOut
from app.service.canon_service import CanonService
from app.service.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/canon", tags=["canon"])


@router.get("", response_model=CanonOut, response_model_exclude_none=True)
async def get_canon(
    project_id: uuid.UUID,
    view: str = "worldview",
    at_chapter: int | None = None,
    chapter: int | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CanonOut:
    """view = worldview|characters|timeline|spaces|events|foreshadowing.

    at_chapter=N 이면 N화 시점의 캐논(버전 이력 기준), chapter=N 이면 N화가 캐논에 넣은
    행 전부(이후 대체된 버전 포함, superseded_at_chapter 로 구분), 둘 다 없으면 현재 캐논.
    둘을 함께 주면 400.
    """
    await ProjectService(session).get_owned(user, project_id)  # 소유권 검사
    data = await CanonService(session).get_view(
        project_id, view, at_chapter=at_chapter, chapter=chapter
    )
    return CanonOut(**data)
