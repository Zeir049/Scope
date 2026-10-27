"""구독(요금제) 테스트. (ENABLE_SUBSCRIPTION)"""
from __future__ import annotations

from httpx import AsyncClient


async def test_subscription_get_and_change(client: AsyncClient, auth_headers: dict):
    r = await client.get("/me/subscription", headers=auth_headers)
    assert r.status_code == 200 and r.json()["plan"] == "free"

    r = await client.put("/me/subscription", json={"plan": "pro"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["plan"] == "pro"
    assert "공유 링크" in r.json()["features"]

    # 알 수 없는 plan → 400
    r = await client.put("/me/subscription", json={"plan": "bogus"}, headers=auth_headers)
    assert r.status_code == 400


async def test_subscription_requires_auth(client: AsyncClient):
    assert (await client.get("/me/subscription")).status_code == 401
