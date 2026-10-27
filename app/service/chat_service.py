"""워크스페이스 채팅 비즈니스 로직. (ENABLE_CHAT)"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.assistant import get_chat_assistant
from app.core.exceptions import NotFoundError
from app.models import ChatSession, User
from app.repository.chat_repo import ChatRepository
from app.repository.project_repo import ProjectRepository
from app.schemas.chat import ChatMessageOut, ChatSessionOut
from app.service.ownership import assert_owned

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.repo = ChatRepository(session)
        self.projects = ProjectRepository(session)

    async def list_sessions(
        self, user: User, project_id: uuid.UUID
    ) -> list[ChatSessionOut]:
        assert_owned(await self.projects.get_by_id(project_id), user)
        rows = await self.repo.list_sessions(project_id)
        return [ChatSessionOut.model_validate(r) for r in rows]

    async def create_session(
        self, user: User, project_id: uuid.UUID, title: str | None
    ) -> ChatSessionOut:
        assert_owned(await self.projects.get_by_id(project_id), user)
        session = await self.repo.create_session(project_id, title or "새 대화")
        await self.s.commit()
        return ChatSessionOut.model_validate(session)

    async def _owned_session(self, user: User, session_id: uuid.UUID) -> ChatSession:
        session = await self.repo.get_session(session_id)
        if session is None:
            raise NotFoundError("대화를 찾을 수 없습니다.")
        assert_owned(await self.projects.get_by_id(session.project_id), user)
        return session

    async def get_messages(
        self, user: User, session_id: uuid.UUID
    ) -> list[ChatMessageOut]:
        await self._owned_session(user, session_id)
        rows = await self.repo.list_messages(session_id)
        return [ChatMessageOut.model_validate(m) for m in rows]

    async def post_message(
        self, user: User, session_id: uuid.UUID, content: str
    ) -> list[ChatMessageOut]:
        session = await self._owned_session(user, session_id)
        history = [
            {"role": m.role, "content": m.content}
            for m in await self.repo.list_messages(session_id)
        ]
        user_msg = await self.repo.add_message(session_id, "user", content)
        reply = await get_chat_assistant().reply(session.project_id, history, content)
        assistant_msg = await self.repo.add_message(session_id, "assistant", reply)
        await self.s.commit()
        return [
            ChatMessageOut.model_validate(user_msg),
            ChatMessageOut.model_validate(assistant_msg),
        ]
