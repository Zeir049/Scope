# ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 삭제. 삭제법은 app/smoke/README.md 참조
"""가짜 LLM. 받은 텍스트를 그대로 돌려주는 에코 왕복.

나중에 진짜 LLM을 붙일 자리다: 이 함수 본문(return text)만 실제 LLM 호출로 바꾸면
나머지(판정·저장·화면)는 그대로 동작한다. 실제 파이프라인(app/pipeline/*)은 건드리지 않음.
'ok/mismatch' 판정(입력==출력)은 라우터가 한다.
"""
from __future__ import annotations


async def fake_llm_roundtrip(text: str) -> str:
    """LLM에 보낼 텍스트를 받아 '응답'을 돌려준다. 지금은 에코(그대로 반환).

    → 진짜 LLM 연결 시 여기만 교체. (예: return await real_llm.complete(text))
    """
    return text
