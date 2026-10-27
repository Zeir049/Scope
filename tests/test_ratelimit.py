"""레이트리밋 테스트 — 기본 테스트 환경은 비활성(conftest), 여기서만 켜서 검증."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import ratelimit
from app.core.config import settings


@pytest.fixture(autouse=True)
def _clean_state():
    ratelimit.reset_state()
    yield
    ratelimit.reset_state()


async def test_general_limit(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 5)
    for _ in range(5):
        assert (await client.get("/health")).status_code == 200
    r = await client.get("/health")
    assert r.status_code == 429 and "요청이 너무 많습니다" in r.text


async def test_auth_stricter_limit(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 100)
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 3)
    for _ in range(3):
        r = await client.post("/auth/login", json={"email": "x@x.com", "password": "wrong1234"})
        assert r.status_code != 429
    r = await client.post("/auth/login", json={"email": "x@x.com", "password": "wrong1234"})
    assert r.status_code == 429  # 무차별 대입 차단

    # 일반 경로는 별도 카운터라 여전히 통과
    assert (await client.get("/health")).status_code == 200


async def test_disabled_when_zero(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0)
    for _ in range(20):
        assert (await client.get("/health")).status_code == 200
