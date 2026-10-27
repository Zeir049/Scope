"""인증 비즈니스 로직. 트랜잭션 경계는 여기서 잡는다."""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthError, ConflictError
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.email.sender import get_email_sender
from app.models import User
from app.repository.reset_repo import PasswordResetRepository
from app.repository.user_repo import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.users = UserRepository(session)
        self.resets = PasswordResetRepository(session)

    async def register(self, body: RegisterRequest) -> TokenResponse:
        if await self.users.get_by_email(body.email):
            raise ConflictError("이미 가입된 이메일입니다.")
        user = await self.users.create(
            email=body.email,
            password_hash=hash_password(body.password),
            name=body.name,
        )
        await self.s.commit()
        logger.info("user registered: %s", user.id)
        return self._token_for(user)

    async def login(self, body: LoginRequest) -> TokenResponse:
        user = await self.users.get_by_email(body.email)
        if user is None or not verify_password(body.password, user.password_hash):
            raise AuthError("이메일 또는 비밀번호가 일치하지 않습니다.")
        return self._token_for(user)

    async def login_with_firebase(self, id_token: str) -> TokenResponse:
        """Firebase ID 토큰 검증 후 이메일 기준 find-or-create → 자체 JWT 발급.

        스키마 변경 없이 기존 users 테이블을 그대로 쓴다. 새로 만드는 계정의
        password_hash는 무작위 값이라 비밀번호 로그인은 불가능(구글 로그인 전용).
        """
        from app.firebase.verifier import get_firebase_verifier

        identity = await get_firebase_verifier().verify(id_token)
        user = await self.users.get_by_email(identity.email)
        if user is None:
            user = await self.users.create(
                email=identity.email,
                password_hash=hash_password(generate_token()),
                name=identity.name,
            )
            await self.s.commit()
            logger.info("user created via firebase: %s", user.id)
        return self._token_for(user)

    # ── 비밀번호 재설정 ───────────────────────────────────
    async def request_reset(self, email: str) -> None:
        """재설정 토큰 발급 + 메일 발송. 계정 존재 여부는 노출하지 않는다."""
        user = await self.users.get_by_email(email)
        if user is None:
            logger.info("reset requested for unknown email (no-op)")
            return
        raw_token = generate_token()
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            minutes=settings.reset_token_expire_minutes
        )
        await self.resets.create(user.id, hash_token(raw_token), expires)
        await self.s.commit()

        link = f"{settings.public_base_url}/reset-password?token={raw_token}"
        await get_email_sender().send(
            to=email,
            subject="[Glitch] 비밀번호 재설정",
            body=f"아래 링크에서 비밀번호를 재설정하세요(유효 {settings.reset_token_expire_minutes}분):\n{link}",
        )

    async def reset_password(self, body: ResetPasswordRequest) -> None:
        row = await self.resets.get_by_hash(hash_token(body.token))
        now = dt.datetime.now(dt.timezone.utc)
        if row is None or row.used or row.expires_at < now:
            raise AuthError("유효하지 않거나 만료된 토큰입니다.")
        user = await self.users.get_by_id(row.user_id)
        if user is None:
            raise AuthError("유효하지 않은 토큰입니다.")
        user.password_hash = hash_password(body.new_password)
        row.used = True
        await self.s.commit()
        logger.info("password reset done: user=%s", user.id)

    @staticmethod
    def _token_for(user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_access_token(str(user.id)),
            user=UserOut.model_validate(user),
        )
