"""융합 1단계 — 프로젝트 목록 보강(page_size·회차 집계·updated_at 갱신) + Project_N 자동 이름."""
from __future__ import annotations

import datetime as dt
import uuid

from httpx import AsyncClient

from tests.util import poll_result


async def _register(client: AsyncClient) -> dict[str, str]:
    sfx = uuid.uuid4().hex[:8]
    r = await client.post(
        "/auth/register",
        json={"email": f"fp_{sfx}@x.com", "password": "secret123", "name": "Other"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _list(client: AsyncClient, h: dict, **params) -> dict:
    r = await client.get("/projects", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _find(body: dict, pid: str) -> dict:
    return next(p for p in body["items"] if p["id"] == pid)


# ── page_size ────────────────────────────────────────────────
async def test_page_size(client: AsyncClient):
    h = await _register(client)
    for i in range(7):
        await client.post("/projects", json={"name": f"p{i}"}, headers=h)

    body = await _list(client, h, page_size=6)
    assert len(body["items"]) == 6
    assert body["total_count"] == 7 and body["total_pages"] == 2
    body2 = await _list(client, h, page_size=6, page=2)
    assert len(body2["items"]) == 1

    assert len((await _list(client, h))["items"]) == 7  # 기본 20


async def test_page_size_out_of_range(client: AsyncClient, auth_headers: dict):
    for bad in (0, 51):
        r = await client.get("/projects", params={"page_size": bad}, headers=auth_headers)
        assert r.status_code == 400
        assert "page_size" in r.json()["detail"]


# ── 회차 집계 ────────────────────────────────────────────────
async def test_chapter_count_and_last_status(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    p = _find(await _list(client, h), pid)
    assert p["chapter_count"] == 0 and p["last_chapter_status"] is None

    for no in (1, 2):
        r = await client.post(
            f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"본문 {no}"}, headers=h
        )
        assert r.status_code == 201
    await client.post(f"/projects/{pid}/chapters/2/extract", headers=h)
    await poll_result(client, pid, 2, h, stop=("extracted", "failed"))

    p = _find(await _list(client, h), pid)
    assert p["chapter_count"] == 2
    assert p["last_chapter_status"] == "extracted"  # 가장 큰 chapter_no(2화)의 상태

    # 단건 조회도 같은 집계를 준다
    single = (await client.get(f"/projects/{pid}", headers=h)).json()
    assert single["chapter_count"] == 2 and single["last_chapter_status"] == "extracted"


async def test_list_is_owner_scoped(client: AsyncClient, auth_headers: dict, project_id: str):
    other = await _register(client)
    body = await _list(client, other)
    assert project_id not in [p["id"] for p in body["items"]]


# ── updated_at 갱신 (회차 생성/상태 전환/삭제) ───────────────
async def test_project_updated_at_touched_by_chapter_changes(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id

    async def updated_at() -> dt.datetime:
        raw = (await client.get(f"/projects/{pid}", headers=h)).json()["updated_at"]
        return dt.datetime.fromisoformat(raw)

    t0 = await updated_at()
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "가"}, headers=h)
    t1 = await updated_at()
    assert t1 > t0  # 생성

    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    await poll_result(client, pid, 1, h, stop=("extracted", "failed"))
    t2 = await updated_at()
    assert t2 > t1  # 워커의 상태 전환(extracting→extracted)

    await client.put(f"/projects/{pid}/chapters/1", json={"text": "나"}, headers=h)
    t3 = await updated_at()
    assert t3 > t2  # 재업로드

    assert (await client.delete(f"/projects/{pid}/chapters/1", headers=h)).status_code == 204
    assert await updated_at() > t3  # 삭제

    # 최근에 손댄 프로젝트가 목록 맨 앞
    await client.post("/projects", json={"name": "나중 프로젝트"}, headers=h)
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 9, "text": "다"}, headers=h)
    assert (await _list(client, h))["items"][0]["id"] == pid


# ── Project_N 자동 이름 ──────────────────────────────────────
async def test_auto_name_project_n(client: AsyncClient):
    h = await _register(client)
    # 첫 프로젝트 → Project_1
    r = await client.post("/projects", json={}, headers=h)
    assert r.status_code == 201 and r.json()["name"] == "Project_1"

    for name in ("Project_3", "Project_x", "MyProject_9", "Project_2a"):
        await client.post("/projects", json={"name": name}, headers=h)
    r = await client.post("/projects", json={"name": ""}, headers=h)
    assert r.json()["name"] == "Project_4"  # 패턴에 맞는 최대값(3) + 1
    r = await client.post("/projects", json={"name": "   "}, headers=h)
    assert r.json()["name"] == "Project_5"  # 공백만이면 비어 있는 것으로 본다

    # 다른 사용자의 Project_N 은 세지 않는다
    other = await _register(client)
    r = await client.post("/projects", json={"name": None}, headers=other)
    assert r.json()["name"] == "Project_1"
