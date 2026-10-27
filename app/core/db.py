"""async SQLAlchemy 세션. 모든 DB I/O는 async (CLAUDE.md 규칙)."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성. 라우터가 service에 넘길 세션을 제공.

    트랜잭션 경계는 service 레이어가 잡는다(이 함수는 세션 수명만 관리).
    """
    async with SessionLocal() as session:
        yield session
