"""Firebase ID 토큰 검증 경계. FIREBASE_MODE로 구현 주입.

- google: 구글 공개키(JWKS)로 서명·발급자·대상(aud)을 실검증한다.
- fake:   "fake:<email>[:<name>]" 형태 토큰을 그대로 신뢰한다.
          pytest / 오프라인 데모 전용 — 실서비스에서 켜면 인증이 무력화된다.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.core.exceptions import AuthError

logger = logging.getLogger(__name__)

# Firebase(securetoken)가 서명에 쓰는 구글 공개키 목록
GOOGLE_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)


@dataclass(frozen=True)
class FirebaseIdentity:
    uid: str
    email: str
    name: str | None = None


class FirebaseVerifier(Protocol):
    async def verify(self, id_token: str) -> FirebaseIdentity: ...


class GoogleFirebaseVerifier:
    """구글 공개키로 RS256 서명을 검증한다. 키는 PyJWKClient가 캐시."""

    def __init__(self, project_id: str) -> None:
        if not project_id:
            raise ValueError("FIREBASE_PROJECT_ID가 설정되지 않았습니다.")
        self.project_id = project_id
        self.jwks = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True)

    async def verify(self, id_token: str) -> FirebaseIdentity:
        # JWKS 첫 조회가 블로킹 HTTP라 스레드로 내린다(이후엔 캐시).
        try:
            return await asyncio.to_thread(self._verify_sync, id_token)
        except AuthError:
            raise
        except Exception as e:  # noqa: BLE001 - 네트워크 등 예기치 못한 실패
            logger.warning("firebase verify failed: %s", e)
            raise AuthError("구글 로그인 검증에 실패했습니다.") from e

    def _verify_sync(self, id_token: str) -> FirebaseIdentity:
        try:
            key = self.jwks.get_signing_key_from_jwt(id_token).key
            payload = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self.project_id,
                issuer=f"https://securetoken.google.com/{self.project_id}",
            )
        except jwt.PyJWTError as e:
            raise AuthError("유효하지 않은 구글 로그인 토큰입니다.") from e

        uid = payload.get("sub") or ""
        email = payload.get("email") or ""
        if not uid or not email:
            raise AuthError("구글 계정에서 이메일을 확인할 수 없습니다.")
        return FirebaseIdentity(uid=uid, email=email, name=payload.get("name"))


class FakeFirebaseVerifier:
    """테스트 전용: "fake:<email>[:<name>]" 토큰을 검증 없이 통과시킨다."""

    async def verify(self, id_token: str) -> FirebaseIdentity:
        parts = id_token.split(":", 2)
        if len(parts) < 2 or parts[0] != "fake" or not parts[1]:
            raise AuthError("유효하지 않은 구글 로그인 토큰입니다.")
        email = parts[1]
        name = parts[2] if len(parts) > 2 and parts[2] else None
        return FirebaseIdentity(uid=f"fake-{email}", email=email, name=name)


@lru_cache
def get_firebase_verifier() -> FirebaseVerifier:
    mode = settings.firebase_mode.lower()
    if mode == "google":
        return GoogleFirebaseVerifier(settings.firebase_project_id)
    if mode == "fake":
        logger.warning("FIREBASE_MODE=fake — 테스트 전용 모드입니다.")
        return FakeFirebaseVerifier()
    raise ValueError(f"알 수 없는 FIREBASE_MODE: {settings.firebase_mode}")
