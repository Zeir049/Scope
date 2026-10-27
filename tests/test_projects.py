"""프로젝트 API 테스트: CRUD + 미존재(404) + 미인증(401) + 권한위반(403)."""
from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_project_crud(client: AsyncClient, auth_headers: dict):
    r = await client.post("/projects", json={"name": "작품A"}, headers=auth_headers)
    assert r.status_code == 201
    pid = r.json()["id"]

    # 목록 형태(페이지네이션)
    r = await client.get("/projects", headers=auth_headers)
    body = r.json()
    assert {"items", "page", "total_pages", "total_count"} <= body.keys()

    r = await client.get(f"/projects/{pid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["name"] == "작품A"

    # 없는 프로젝트 → 404
    r = await client.get(f"/projects/{uuid.uuid4()}", headers=auth_headers)
    assert r.status_code == 404

    # 삭제 → 204, 이후 404
    assert (await client.delete(f"/projects/{pid}", headers=auth_headers)).status_code == 204
    assert (await client.get(f"/projects/{pid}", headers=auth_headers)).status_code == 404


async def test_projects_require_auth(client: AsyncClient):
    assert (await client.get("/projects")).status_code == 401


async def test_search_filter(client: AsyncClient, auth_headers: dict):
    uniq = uuid.uuid4().hex[:6]
    await client.post("/projects", json={"name": f"검색대상-{uniq}"}, headers=auth_headers)
    r = await client.get(f"/projects?q={uniq}", headers=auth_headers)
    items = r.json()["items"]
    assert all(uniq in p["name"] for p in items) and items


async def test_ownership_forbidden(client: AsyncClient, auth_headers: dict, project_id: str):
    # 다른 사용자
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert (await client.get(f"/projects/{project_id}", headers=h2)).status_code == 403
    assert (await client.delete(f"/projects/{project_id}", headers=h2)).status_code == 403
