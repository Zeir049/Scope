"""워크스페이스 채팅 테스트. (ENABLE_CHAT)"""
from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_chat_session_and_messages(client: AsyncClient, auth_headers: dict, project_id: str):
    r = await client.post(
        f"/projects/{project_id}/chats", json={"title": "첫 대화"}, headers=auth_headers
    )
    assert r.status_code == 201
    sid = r.json()["id"]

    r = await client.get(f"/projects/{project_id}/chats", headers=auth_headers)
    assert any(s["id"] == sid for s in r.json())

    # 메시지 전송 → [user, assistant] 반환
    r = await client.post(
        f"/chats/{sid}/messages",
        json={"content": "이 작품의 주제가 뭐야?"},
        headers=auth_headers,
    )
    msgs = r.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"

    # 히스토리 조회
    r = await client.get(f"/chats/{sid}/messages", headers=auth_headers)
    assert len(r.json()) == 2


async def test_chat_missing_session_404(client: AsyncClient, auth_headers: dict):
    r = await client.get(f"/chats/{uuid.uuid4()}/messages", headers=auth_headers)
    assert r.status_code == 404


async def test_chat_ownership(client: AsyncClient, auth_headers: dict, project_id: str):
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = await client.post(f"/projects/{project_id}/chats", json={}, headers=h2)
    assert r.status_code == 403
