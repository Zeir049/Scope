"""채팅 어시스턴트 경계. CHAT_MODE로 구현 주입(지금은 Fake).

진짜 LLM 어시스턴트는 RemoteChatAssistant를 추가하고 factory에 한 줄 더하면
교체된다. 파이프라인과 동일한 '인터페이스 뒤로 분리' 패턴.
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class ChatAssistant(Protocol):
    async def reply(
        self, project_id: uuid.UUID, history: list[dict], message: str
    ) -> str:
        ...


class FakeChatAssistant:
    async def reply(
        self, project_id: uuid.UUID, history: list[dict], message: str
    ) -> str:
        snippet = message.strip()[:40]
        return (
            f"(예시 어시스턴트) '{snippet}' 에 대한 답변입니다. "
            "실제 응답은 LLM 어시스턴트 연결 시 제공됩니다."
        )


@lru_cache
def get_chat_assistant() -> ChatAssistant:
    mode = settings.chat_mode.lower()
    if mode == "fake":
        return FakeChatAssistant()
    # if mode == "remote": return RemoteChatAssistant(...)
    raise ValueError(f"알 수 없는 CHAT_MODE: {settings.chat_mode}")
