"""공유 링크 테스트. (ENABLE_SHARING)"""
from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_share_create_view_revoke(client: AsyncClient, auth_headers: dict, project_id: str):
    await client.post(
        f"/projects/{project_id}/chapters",
        json={"chapter_no": 1, "text": "본문"},
        headers=auth_headers,
    )

    r = await client.post(f"/projects/{project_id}/share", headers=auth_headers)
    assert r.status_code == 201
    token = r.json()["token"]
    link_id = r.json()["id"]
    assert r.json()["url"].endswith(token)

    # 활성 링크 재요청 → 같은 토큰 재사용
    r2 = await client.post(f"/projects/{project_id}/share", headers=auth_headers)
    assert r2.json()["token"] == token

    # 목록
    r = await client.get(f"/projects/{project_id}/shares", headers=auth_headers)
    assert len(r.json()) >= 1

    # 공개 조회(인증 없이)
    r = await client.get(f"/shared/{token}")
    assert r.status_code == 200
    assert r.json()["project"]["id"] == project_id
    assert len(r.json()["chapters"]) == 1

    # 폐기 → 공개 조회 404
    assert (await client.delete(f"/shares/{link_id}", headers=auth_headers)).status_code == 204
    assert (await client.get(f"/shared/{token}")).status_code == 404


async def test_share_invalid_token_404(client: AsyncClient):
    assert (await client.get("/shared/does-not-exist")).status_code == 404


async def test_share_ownership(client: AsyncClient, auth_headers: dict, project_id: str):
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert (await client.post(f"/projects/{project_id}/share", headers=h2)).status_code == 403
