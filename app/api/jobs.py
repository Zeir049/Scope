"""진행 중 분석 작업 라우터 — 프론트 '작업 창'이 새로고침 후에도 진행 상황을 복원하는 용도."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.schemas.job import ActiveJobsOut
from app.service.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/active", response_model=ActiveJobsOut)
async def list_active_jobs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ActiveJobsOut:
    """내 프로젝트에서 추출/검수 중인 회차 목록 (chapters.status 기준)."""
    return await JobService(session).list_active(user)
