"""분석 파이프라인 연결 점검.

CLAUDE.md 불변원칙 1: 파이프라인은 service 레이어에서, 주입받은 AnalysisPipeline
인터페이스로만 호출한다. 프론트는 분석(업로드) 전에 이걸로 AI 서버가 살아 있는지 본다.
"""
from __future__ import annotations

import logging

from app.pipeline.factory import get_pipeline
from app.pipeline.interface import PipelineHealth

logger = logging.getLogger(__name__)


class PipelineService:
    async def check_health(self) -> PipelineHealth:
        health = await get_pipeline().health()
        if health.ok:
            logger.info("pipeline health ok: mode=%s", health.mode)
        else:
            logger.warning("pipeline health DOWN: mode=%s message=%s", health.mode, health.message)
        # 부가 정보(AI 서버 /health 응답 등)는 응답에 싣지 않고 로그로만 남긴다
        if health.info:
            logger.info("pipeline health info: mode=%s info=%s", health.mode, health.info)
        return health
