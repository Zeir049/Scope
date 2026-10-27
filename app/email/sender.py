"""메일 발송 경계. EMAIL_MODE로 구현 주입(지금은 콘솔 로깅).

진짜 SMTP/SES는 SmtpEmailSender를 추가하고 factory에 한 줄 더하면 된다.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """개발용: 실제 발송 대신 로그로 출력."""

    async def send(self, to: str, subject: str, body: str) -> None:
        logger.info("[EMAIL] to=%s subject=%s\n%s", to, subject, body)


@lru_cache
def get_email_sender() -> EmailSender:
    mode = settings.email_mode.lower()
    if mode == "console":
        return ConsoleEmailSender()
    # if mode == "smtp": return SmtpEmailSender(...)
    raise ValueError(f"알 수 없는 EMAIL_MODE: {settings.email_mode}")
