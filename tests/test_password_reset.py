"""비밀번호 재설정 흐름 테스트."""
from __future__ import annotations

import datetime as dt
import uuid

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_token
from app.repository.reset_repo import PasswordResetRepository


async def test_forgot_password_generic_200(client: AsyncClient):
    # 계정 존재 여부와 무관하게 항상 동일 응답
    r = await client.post("/auth/forgot-password", json={"email": "nobody@x.com"})
    assert r.status_code == 200


async def test_reset_password_flow(client: AsyncClient):
    email = f"r_{uuid.uuid4().hex[:8]}@x.com"
    r = await client.post(
        "/auth/register", json={"email": email, "password": "oldpass123"}
    )
    user_id = uuid.UUID(r.json()["user"]["id"])

    # 원본 토큰을 알기 위해 직접 주입(해시만 저장됨)
    raw = "known-reset-token-123"
    async with SessionLocal() as s:
        await PasswordResetRepository(s).create(
            user_id,
            hash_token(raw),
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30),
        )
        await s.commit()

    # 재설정
    r = await client.post(
        "/auth/reset-password", json={"token": raw, "new_password": "newpass123"}
    )
    assert r.status_code == 200

    # 옛 비번 실패, 새 비번 성공
    assert (await client.post("/auth/login", json={"email": email, "password": "oldpass123"})).status_code == 401
    assert (await client.post("/auth/login", json={"email": email, "password": "newpass123"})).status_code == 200

    # 토큰 재사용 → 401
    r = await client.post(
        "/auth/reset-password", json={"token": raw, "new_password": "another123"}
    )
    assert r.status_code == 401


async def test_reset_invalid_token_401(client: AsyncClient):
    r = await client.post(
        "/auth/reset-password", json={"token": "nope", "new_password": "x123456"}
    )
    assert r.status_code == 401
