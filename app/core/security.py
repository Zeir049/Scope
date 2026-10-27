"""비밀번호 해시(bcrypt) + JWT 발급/검증 + 무작위 토큰. 인증 로직은 여기에만."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthError


# ── 비밀번호 ──────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# ── JWT ───────────────────────────────────────────────────
def create_access_token(user_id: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """토큰 검증 후 user_id(sub) 반환. 실패 시 AuthError(401)."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("토큰이 만료되었습니다.") from e
    except jwt.PyJWTError as e:
        raise AuthError("유효하지 않은 토큰입니다.") from e

    sub = payload.get("sub")
    if not sub:
        raise AuthError("유효하지 않은 토큰입니다.")
    return str(sub)


# ── 무작위 토큰 (비밀번호 재설정 / 공유 링크) ────────────────
def generate_token(nbytes: int = 32) -> str:
    """URL 안전한 무작위 토큰(원본). 사용자에게 전달되는 값."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """토큰은 해시로만 저장한다(유출 대비)."""
    return hashlib.sha256(token.encode()).hexdigest()
