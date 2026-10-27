"""GET /jobs/active — chapters.status 에서 파생한 진행 중 작업 목록 (D7)."""
from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from tests.util import poll_result


async def _register(client: AsyncClient) -> dict[str, str]:
    sfx = uuid.uuid4().hex[:8]
    r = await client.post(
        "/auth/register",
        json={"email": f"ja_{sfx}@x.com", "password": "secret123", "name": "Other"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _active(client: AsyncClient, h: dict) -> list[dict]:
    r = await client.get("/jobs/active", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_active_job_lifecycle(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    assert await _active(client, h) == []

    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "title": "첫 화", "text": "본문"}, headers=h)
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)  # FakePipeline 1초 지연

    items = await _active(client, h)
    assert len(items) == 1
    job = items[0]
    assert job["project_id"] == pid and job["project_name"] == "테스트작품"
    assert job["chapter_no"] == 1 and job["title"] == "첫 화"
    assert job["status"] == "extracting"
    assert job["progress"] == 0
    assert job["started_at"] and job["stale"] is False

    await poll_result(client, pid, 1, h, stop=("extracted", "failed"))
    assert await _active(client, h) == []  # 완료 후 0건

    # 검수 중에도 보인다
    await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    items = await _active(client, h)
    assert [j["status"] for j in items] == ["reviewing"]
    await poll_result(client, pid, 1, h, stop=("saved", "failed"))
    assert await _active(client, h) == []


async def test_active_jobs_owner_scoped(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)

    other = await _register(client)
    assert await _active(client, other) == []  # 남의 작업은 안 보인다
    assert len(await _active(client, h)) == 1
    await poll_result(client, pid, 1, h, stop=("extracted", "failed"))


async def test_active_job_stale_flag(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    async with SessionLocal() as s:  # 워커 없이 진행 중으로 두고 오래된 것처럼
        await s.execute(
            text(
                "UPDATE chapters SET status = 'reviewing',"
                " updated_at = now() - make_interval(mins => :m)"
                " WHERE project_id = :p AND chapter_no = 1"
            ),
            {"m": settings.analysis_stale_threshold_minutes + 1, "p": uuid.UUID(pid)},
        )
        await s.commit()

    items = await _active(client, h)
    assert len(items) == 1 and items[0]["stale"] is True and items[0]["progress"] is None
    # 조회는 표시만 — 상태를 바꾸지 않는다
    d = (await client.get(f"/projects/{pid}/chapters/1", headers=h)).json()
    assert d["status"] == "reviewing"


async def test_active_jobs_requires_auth(client: AsyncClient):
    assert (await client.get("/jobs/active")).status_code == 401
