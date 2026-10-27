"""POST /auth/firebase — fake 검증기로 교환 흐름 테스트.

실 구글 검증(GoogleFirebaseVerifier)은 네트워크가 필요해 여기서 다루지 않는다.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.firebase.verifier import get_firebase_verifier


@pytest.fixture(autouse=True)
def _fake_firebase(monkeypatch):
    monkeypatch.setattr(settings, "firebase_mode", "fake")
    get_firebase_verifier.cache_clear()
    yield
    get_firebase_verifier.cache_clear()


async def test_firebase_login_creates_user_once(client: AsyncClient):
    email = f"g_{uuid.uuid4().hex[:8]}@gmail.com"

    # 첫 로그인 → 계정 자동 생성
    r = await client.post("/auth/firebase", json={"id_token": f"fake:{email}:구글러"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert body["user"]["name"] == "구글러"
    user_id = body["user"]["id"]

    # 발급된 JWT로 보호 라우트 접근 가능
    r = await client.get(
        "/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert r.status_code == 200 and r.json()["email"] == email

    # 두 번째 로그인 → 같은 계정 재사용(중복 생성 없음)
    r = await client.post("/auth/firebase", json={"id_token": f"fake:{email}"})
    assert r.status_code == 200
    assert r.json()["user"]["id"] == user_id


async def test_firebase_login_bad_token_401(client: AsyncClient):
    r = await client.post("/auth/firebase", json={"id_token": "not-a-fake-token"})
    assert r.status_code == 401


async def test_firebase_created_user_cannot_password_login(client: AsyncClient):
    email = f"g_{uuid.uuid4().hex[:8]}@gmail.com"
    r = await client.post("/auth/firebase", json={"id_token": f"fake:{email}"})
    assert r.status_code == 200

    # 무작위 password_hash라 어떤 비밀번호로도 로그인 불가
    r = await client.post("/auth/login", json={"email": email, "password": "guess123"})
    assert r.status_code == 401
