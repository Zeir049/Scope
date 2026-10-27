from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PasswordResetToken


class PasswordResetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(
        self, user_id: uuid.UUID, token_hash: str, expires_at: dt.datetime
    ) -> PasswordResetToken:
        row = PasswordResetToken(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        self.s.add(row)
        await self.s.flush()
        return row

    async def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        # 가장 최근 발급분을 사용(토큰 해시는 유니크 제약이 없으므로 first 사용)
        res = await self.s.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .order_by(PasswordResetToken.created_at.desc())
            .limit(1)
        )
        return res.scalars().first()
