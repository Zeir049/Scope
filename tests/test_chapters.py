"""회차 API 테스트: 업로드(JSON/파일) + 중복(409) + 권한(403)."""
from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_upload_json_and_file(client: AsyncClient, auth_headers: dict, project_id: str):
    # JSON 텍스트 업로드
    r = await client.post(
        f"/projects/{project_id}/chapters",
        json={"chapter_no": 1, "title": "1화", "text": "본문 텍스트"},
        headers=auth_headers,
    )
    assert r.status_code == 201 and r.json()["status"] == "uploaded"

    # 같은 회차번호 → 409
    r = await client.post(
        f"/projects/{project_id}/chapters",
        json={"chapter_no": 1, "text": "중복"},
        headers=auth_headers,
    )
    assert r.status_code == 409

    # 파일(multipart) 업로드
    r = await client.post(
        f"/projects/{project_id}/chapters",
        data={"chapter_no": "2", "title": "2화"},
        files={"file": ("2.txt", "파일 본문".encode(), "text/plain")},
        headers=auth_headers,
    )
    assert r.status_code == 201

    # 목록 = 2
    r = await client.get(f"/projects/{project_id}/chapters", headers=auth_headers)
    assert len(r.json()["items"]) == 2


async def test_upload_validation_400(client: AsyncClient, auth_headers: dict, project_id: str):
    # text/file 둘 다 없음
    r = await client.post(
        f"/projects/{project_id}/chapters",
        data={"chapter_no": "1"},
        files={"dummy": ("d", b"", "text/plain")},
        headers=auth_headers,
    )
    assert r.status_code == 400


async def test_chapter_ownership(client: AsyncClient, auth_headers: dict, project_id: str):
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = await client.post(
        f"/projects/{project_id}/chapters",
        json={"chapter_no": 1, "text": "침입"},
        headers=h2,
    )
    assert r.status_code == 403
