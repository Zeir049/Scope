"""파이프라인 연결 점검 응답."""
from __future__ import annotations

from pydantic import BaseModel


class PipelineHealthOut(BaseModel):
    """GET /pipeline/health. 연결 실패도 200 + ok=false 로 내려준다(원인은 message).

    구현체가 준 부가 정보(PipelineHealth.info — AI 서버 /health 응답, llm 모드면 data_root 경로 등)는
    내부 정보라 응답에 싣지 않고 서버 로그에만 남긴다(PipelineService).
    """

    ok: bool
    mode: str  # fake | remote | local
    message: str = ""
