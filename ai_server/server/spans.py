"""원문 인용 → 문자 오프셋. echo 검수와 scope_ai 검수가 함께 쓴다."""
from __future__ import annotations

import logging

from server.schemas import Span

logger = logging.getLogger("glitch-ai")

_QUOTE_MARKS = "\"'“”‘’「」『』"


def span_of(text: str, quote: str) -> Span:
    """인용문의 문자 오프셋을 원문에서 직접 찾는다.

    LLM 에게 start/end 를 세라고 시키면 거의 틀리므로, 프롬프트에서는
    quote 만 받고 오프셋은 항상 서버가 계산한다. 못 찾으면 0,0 으로 두고
    경고만 남긴다 (몸통이 하이라이트를 그리지 못할 뿐 분석은 살린다).
    """
    if not quote:
        return Span(start=0, end=0, quote="")
    # 모델이 인용문을 따옴표로 한 번 더 감싸는 경우가 있어 벗긴 형태도 찾아본다.
    for candidate in (quote, quote.strip().strip(_QUOTE_MARKS).strip()):
        index = text.find(candidate) if candidate else -1
        if index >= 0:
            return Span(start=index, end=index + len(candidate), quote=candidate)
    logger.warning("인용문을 원문에서 찾지 못함: %r", quote[:40])
    return Span(start=0, end=0, quote=quote)
