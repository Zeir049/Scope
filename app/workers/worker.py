"""arq 워커 설정 — 분석 작업을 API 서버와 다른 프로세스에서 실행한다.

실행:  .venv\\Scripts\\python.exe -m arq app.workers.worker.WorkerSettings
(QUEUE_MODE=arq 이고 Redis(docker compose up -d redis → glitch-redis)가 떠 있어야 한다.
 start_integrated.bat / start_tunnel.bat 이 [Glitch Worker] 창으로 띄운다.)
분석 큐는 arq 로 통일한다. inline 은 테스트 전용(conftest 가 QUEUE_MODE=inline 으로 덮어씀).

작업 함수는 app/workers/tasks.py의 기존 함수를 그대로 감싼다 — 실행 위치만
바뀌고 로직은 동일. 진행 상태는 DB(chapters.status)가 단일 원천이므로 arq의
결과 저장은 쓰지 않는다(keep_result=0 → 같은 job_id 즉시 재사용 가능).
"""
from __future__ import annotations

import logging
import uuid

from arq.connections import RedisSettings

from app.core.config import settings
from app.workers import tasks

logger = logging.getLogger(__name__)


async def extract_job(ctx: dict, project_id: str, chapter_no: int) -> None:
    await tasks.run_extraction(uuid.UUID(project_id), chapter_no)


async def review_job(
    ctx: dict, project_id: str, chapter_no: int, auto_save: bool = False
) -> None:
    await tasks.run_review(uuid.UUID(project_id), chapter_no, auto_save=auto_save)


async def full_job(ctx: dict, project_id: str, chapter_no: int) -> None:
    await tasks.run_full_analysis(uuid.UUID(project_id), chapter_no)


async def on_startup(ctx: dict) -> None:
    from app.core.logging import setup_logging

    setup_logging("worker")  # 콘솔 + logs/worker.log
    logger.info(
        "glitch worker started: pipeline=%s redis=%s", settings.pipeline_mode, settings.redis_url
    )


async def on_shutdown(ctx: dict) -> None:
    from app.core.db import engine

    await engine.dispose()
    logger.info("glitch worker stopped")


class WorkerSettings:
    functions = [extract_job, review_job, full_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 4                              # 동시 분석 수
    # 기본 900초. 파이프라인 HTTP 타임아웃(300초 × 검수의 임베딩+LLM 2회)보다 넉넉하게.
    # 이 시간을 넘겨 끊긴 작업은 상태가 extracting/reviewing 으로 남는다 →
    # ANALYSIS_STALE_MINUTES 가 지나면 다음 요청이 failed 로 정리하고 받아준다(D8).
    job_timeout = settings.job_timeout_seconds
    keep_result = 0                           # 상태는 DB가 단일 원천
    max_tries = 1                             # 재시도 없음 — 재실행이 상태를 꼬이게 하지 않도록.
                                              # 실패는 tasks 가 failed 로 기록한다
