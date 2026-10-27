"""arq 작업 큐 경로 테스트 — Redis가 떠 있을 때만 실행(없으면 skip).

enqueue_analysis(arq) → Redis 큐 → 같은 프로세스의 burst 워커로 소진 → DB 상태 reviewed.
별도 워커 프로세스 없이 arq 경로(직렬화·job_id 중복 방지·워커 함수 배선)를 검증한다.
기본 테스트 환경은 QUEUE_MODE=inline(conftest) — 이 파일만 arq로 바꿔 돈다.
"""
from __future__ import annotations

import pytest
from arq import Worker
from arq.connections import RedisSettings
from httpx import AsyncClient

from app.core.config import settings
from app.workers.queue import enqueue_analysis
from app.workers.worker import WorkerSettings
from tests.util import poll_result


async def _redis_available() -> bool:
    try:
        from arq import create_pool

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.ping()
        await pool.aclose()
        return True
    except Exception:  # noqa: BLE001 - 연결 실패 = Redis 없음
        return False


async def test_arq_queue_roundtrip(client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch):
    if not await _redis_available():
        pytest.skip("Redis 없음 — arq 경로 테스트 건너뜀 (docker compose up -d redis)")
    monkeypatch.setattr(settings, "queue_mode", "arq")
    h, pid = auth_headers, project_id

    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "큐 테스트 본문"}, headers=h
    )
    assert r.status_code == 201, r.text

    # 투입: 202 + 상태 extracting (워커가 아직 안 돌았으므로 진행 안 됨)
    assert (await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)).status_code == 202
    res = (await client.get(f"/projects/{pid}/chapters/1/result", headers=h)).json()
    assert res["status"] == "extracting"

    # 같은 회차 중복 투입은 job_id로 무시된다 (예외 없이 통과)
    import uuid as _uuid

    await enqueue_analysis("full", _uuid.UUID(pid), 1)

    # burst 워커: 큐에 쌓인 작업을 처리하고 종료 (on_shutdown은 테스트 엔진 보호 위해 제외)
    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        burst=True,
        keep_result=0,
        max_tries=1,
        poll_delay=0.1,
    )
    await worker.main()
    await worker.close()

    res = await poll_result(client, pid, 1, h)
    assert res["status"] == "reviewed"
    assert "highlighted_text" in res
