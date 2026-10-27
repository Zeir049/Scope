"""Claude API 공통 호출 클라이언트."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MODEL_NAME = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 8192


def create_client():
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ImportError(
            "Claude 호출에는 'anthropic' 패키지가 필요합니다. requirements.txt를 설치하세요."
        ) from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY가 설정되어 있지 않습니다. "
            "프로젝트 루트의 .env 또는 서버 환경변수를 확인하세요."
        )
    return Anthropic(api_key=api_key)


def call_claude(
    user_text: str,
    system_prompt: str,
    *,
    model: str = MODEL_NAME,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    response = create_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_text}],
    )

    return "\n".join(
        block.text
        for block in response.content
        if block.type == "text"
    )
