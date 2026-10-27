"""워크스페이스 채팅 라우터. (ENABLE_CHAT)"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageOut,
    ChatSessionCreate,
    ChatSessionOut,
)
from app.service.chat_service import ChatService

router = APIRouter(tags=["chat"])


@router.get("/projects/{project_id}/chats", response_model=list[ChatSessionOut])
async def list_chats(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChatSessionOut]:
    return await ChatService(session).list_sessions(user, project_id)


@router.post("/projects/{project_id}/chats", response_model=ChatSessionOut, status_code=201)
async def create_chat(
    project_id: uuid.UUID,
    body: ChatSessionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatSessionOut:
    return await ChatService(session).create_session(user, project_id, body.title)


@router.get("/chats/{session_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageOut]:
    return await ChatService(session).get_messages(user, session_id)


@router.post("/chats/{session_id}/messages", response_model=list[ChatMessageOut])
async def post_message(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageOut]:
    """사용자 메시지 저장 + 어시스턴트 응답 반환([user, assistant])."""
    return await ChatService(session).post_message(user, session_id, body.content)
