"""분석 파이프라인 연결 점검 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User
from app.schemas.pipeline import PipelineHealthOut
from app.service.pipeline_service import PipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/health", response_model=PipelineHealthOut)
async def pipeline_health(_: User = Depends(get_current_user)) -> PipelineHealthOut:
    """분석 시작 전 사전 점검: 백엔드 → AI 서버 연결 확인. LLM 은 호출하지 않는다."""
    health = await PipelineService().check_health()
    return PipelineHealthOut(ok=health.ok, mode=health.mode, message=health.message)
