from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_by_email(self, email: str) -> User | None:
        res = await self.s.execute(select(User).where(User.email == email))
        return res.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.s.get(User, user_id)

    async def create(self, email: str, password_hash: str, name: str | None) -> User:
        user = User(email=email, password_hash=password_hash, name=name)
        self.s.add(user)
        await self.s.flush()  # id 확보 (commit은 service가)
        return user
