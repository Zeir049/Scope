"""인증 API 테스트: 정상 + 중복(409) + 인증실패(401)."""
from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_register_login_flow(client: AsyncClient):
    email = f"a_{uuid.uuid4().hex[:8]}@x.com"
    r = await client.post(
        "/auth/register", json={"email": email, "password": "secret123", "name": "n"}
    )
    assert r.status_code == 201
    assert r.json()["access_token"]
    assert r.json()["user"]["email"] == email

    # 중복 이메일 → 409
    r = await client.post("/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 409

    # 로그인 성공/실패
    r = await client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200
    r = await client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 401


async def test_register_short_password_422(client: AsyncClient):
    r = await client.post(
        "/auth/register",
        json={"email": f"b_{uuid.uuid4().hex[:8]}@x.com", "password": "123"},
    )
    assert r.status_code == 422  # min_length 검증


async def test_me_requires_auth(client: AsyncClient, auth_headers: dict):
    assert (await client.get("/me")).status_code == 401
    r = await client.get("/me", headers=auth_headers)
    assert r.status_code == 200 and "email" in r.json()


async def test_logout(client: AsyncClient, auth_headers: dict):
    assert (await client.post("/auth/logout", headers=auth_headers)).status_code == 204
