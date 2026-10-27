"""모순 판정(✓/✕) — PATCH .../contradictions/{id} + result 반영."""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.util import MANUAL_SAVE, poll_result


async def _register(client: AsyncClient) -> dict[str, str]:
    sfx = uuid.uuid4().hex[:8]
    r = await client.post(
        "/auth/register",
        json={"email": f"cs_{sfx}@x.com", "password": "secret123", "name": "Other"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _run(client: AsyncClient, pid: str, h: dict, no: int, save: bool) -> dict:
    await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"{no}화 본문"}, headers=h
    )
    await client.post(f"/projects/{pid}/chapters/{no}/extract", headers=h)
    await poll_result(client, pid, no, h, stop=("extracted", "failed"))
    await client.post(f"/projects/{pid}/chapters/{no}/review", json=MANUAL_SAVE, headers=h)
    res = await poll_result(client, pid, no, h)
    assert res["status"] == "reviewed"
    if save:
        await client.post(f"/projects/{pid}/chapters/{no}/save", headers=h)
    return res


async def _setup(client: AsyncClient, pid: str, h: dict) -> str:
    """1화 저장 → 2화 검수(모순 발생). 2화 모순 id 반환."""
    await _run(client, pid, h, 1, save=True)
    res = await _run(client, pid, h, 2, save=False)
    items = res["contradictions"]
    assert items and all(c["status"] == "pending" and c["id"] for c in items)
    return items[0]["id"]


def _url(pid: str, no: int, cid: str) -> str:
    return f"/projects/{pid}/chapters/{no}/contradictions/{cid}"


async def test_patch_status_and_result_reflects(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    cid = await _setup(client, pid, h)

    r = await client.patch(_url(pid, 2, cid), json={"status": "confirmed"}, headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == cid and r.json()["status"] == "confirmed"

    res = (await client.get(f"/projects/{pid}/chapters/2/result", headers=h)).json()
    assert next(c for c in res["contradictions"] if c["id"] == cid)["status"] == "confirmed"
    assert res["status"] == "reviewed"  # 판정은 회차 진행 상태를 바꾸지 않는다

    r = await client.patch(_url(pid, 2, cid), json={"status": "dismissed"}, headers=h)
    assert r.json()["status"] == "dismissed"
    r = await client.patch(_url(pid, 2, cid), json={"status": "pending"}, headers=h)
    assert r.json()["status"] == "pending"

    # 저장 후에도 판정은 가능하고 result 에 남는다
    await client.post(f"/projects/{pid}/chapters/2/save", headers=h)
    r = await client.patch(_url(pid, 2, cid), json={"status": "confirmed"}, headers=h)
    assert r.status_code == 200
    res = (await client.get(f"/projects/{pid}/chapters/2/result", headers=h)).json()
    assert res["status"] == "saved"
    assert next(c for c in res["contradictions"] if c["id"] == cid)["status"] == "confirmed"


async def test_patch_invalid_status_is_400(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    cid = await _setup(client, pid, h)
    r = await client.patch(_url(pid, 2, cid), json={"status": "maybe"}, headers=h)
    assert r.status_code == 400


async def test_patch_forbidden(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    cid = await _setup(client, pid, h)
    other = await _register(client)
    r = await client.patch(_url(pid, 2, cid), json={"status": "confirmed"}, headers=other)
    assert r.status_code == 403


async def test_patch_missing_or_wrong_chapter(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    cid = await _setup(client, pid, h)
    # 없는 모순 id
    r = await client.patch(_url(pid, 2, str(uuid.uuid4())), json={"status": "confirmed"}, headers=h)
    assert r.status_code == 404
    # 다른 회차(1화) 경로로 2화의 모순을 고치려 하면 404
    r = await client.patch(_url(pid, 1, cid), json={"status": "confirmed"}, headers=h)
    assert r.status_code == 404
    # 없는 회차 / 없는 프로젝트
    assert (await client.patch(_url(pid, 99, cid), json={"status": "confirmed"}, headers=h)).status_code == 404
    r = await client.patch(_url(str(uuid.uuid4()), 2, cid), json={"status": "confirmed"}, headers=h)
    assert r.status_code == 404
