"""분석 작업 큐 경계. QUEUE_MODE로 실행 방식을 주입한다.

- inline: 서버 프로세스 안에서 asyncio 태스크로 실행 (테스트/단순 개발용).
          서버가 죽으면 진행 중 작업도 사라진다.
- arq:    Redis 큐에 넣고 별도 워커 프로세스(app/workers/worker.py)가 실행.
          서버 재시작에도 대기 작업 보존, 워커 수평 확장, 긴 LLM 호출이
          API 서버를 점유하지 않음.

라우터는 enqueue_analysis() 하나만 부른다 — 어느 모드든 호출부는 동일.
작업 정체성은 (project, chapter) — 같은 회차에 동시에 두 작업이 돌지 않게
arq job_id로 중복 투입을 막는다.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.core.config import settings
from app.workers import tasks

logger = logging.getLogger(__name__)

# kind → (inline 실행 함수, arq 워커 함수 이름)
JOBS: dict[str, tuple[Any, str]] = {
    "extract": (tasks.run_extraction, "extract_job"),
    "review": (tasks.run_review, "review_job"),
    "full": (tasks.run_full_analysis, "full_job"),
}

_inline_tasks: set[asyncio.Task] = set()  # fire-and-forget 태스크 GC 방지
_arq_pool: Any = None
_arq_pool_loop: asyncio.AbstractEventLoop | None = None


def job_id(project_id: uuid.UUID, chapter_no: int) -> str:
    return f"analysis:{project_id}:{chapter_no}"


async def _get_arq_pool() -> Any:
    """이벤트 루프당 1개의 Redis 풀 (테스트는 루프가 바뀌므로 루프 기준 캐시)."""
    global _arq_pool, _arq_pool_loop
    loop = asyncio.get_running_loop()
    if _arq_pool is None or _arq_pool_loop is not loop:
        from arq import create_pool
        from arq.connections import RedisSettings

        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        _arq_pool_loop = loop
    return _arq_pool


async def enqueue_analysis(
    kind: str, project_id: uuid.UUID, chapter_no: int, **opts: Any
) -> None:
    """분석 작업 투입. kind = extract | review | full.

    opts 는 작업 함수 인자로 그대로 넘긴다(예: review 의 auto_save). 상태·DB에 저장하지 않는다.
    """
    if kind not in JOBS:
        raise ValueError(f"알 수 없는 작업 종류: {kind}")
    inline_fn, worker_fn_name = JOBS[kind]

    if settings.queue_mode == "arq":
        pool = await _get_arq_pool()
        job = await pool.enqueue_job(
            worker_fn_name, str(project_id), chapter_no,
            _job_id=job_id(project_id, chapter_no),
            **opts,
        )
        if job is None:
            logger.warning("job already queued/running: %s ch=%s", project_id, chapter_no)
        else:
            logger.info("job enqueued(arq): %s project=%s ch=%s", kind, project_id, chapter_no)
        return

    if settings.queue_mode != "inline":
        raise ValueError(f"알 수 없는 QUEUE_MODE: {settings.queue_mode}")

    task = asyncio.create_task(inline_fn(project_id, chapter_no, **opts))
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)
    logger.info("job started(inline): %s project=%s ch=%s", kind, project_id, chapter_no)
