from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatSession


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list_sessions(self, project_id: uuid.UUID) -> list[ChatSession]:
        res = await self.s.execute(
            select(ChatSession)
            .where(ChatSession.project_id == project_id)
            .order_by(ChatSession.created_at.desc())
        )
        return list(res.scalars().all())

    async def create_session(self, project_id: uuid.UUID, title: str) -> ChatSession:
        session = ChatSession(project_id=project_id, title=title)
        self.s.add(session)
        await self.s.flush()
        return session

    async def get_session(self, session_id: uuid.UUID) -> ChatSession | None:
        return await self.s.get(ChatSession, session_id)

    async def list_messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        res = await self.s.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(res.scalars().all())

    async def add_message(
        self, session_id: uuid.UUID, role: str, content: str
    ) -> ChatMessage:
        msg = ChatMessage(session_id=session_id, role=role, content=content)
        self.s.add(msg)
        await self.s.flush()
        return msg
