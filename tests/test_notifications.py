"""알림 테스트. (ENABLE_NOTIFICATIONS) — 분석 완료 시 알림 생성."""
from __future__ import annotations

from httpx import AsyncClient

from tests.util import poll_result


async def test_notification_created_on_analysis(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)
    await poll_result(client, pid, 1, h)

    r = await client.get("/notifications", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    notif_id = r.json()[0]["id"]

    # 단건 읽음
    assert (await client.post(f"/notifications/{notif_id}/read", headers=h)).status_code == 204
    # 전체 읽음
    assert (await client.post("/notifications/read-all", headers=h)).status_code == 204
    # 안읽음 필터 → 0
    r = await client.get("/notifications?unread_only=true", headers=h)
    assert r.json() == []


async def test_notifications_require_auth(client: AsyncClient):
    assert (await client.get("/notifications")).status_code == 401
