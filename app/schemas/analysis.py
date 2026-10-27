"""분석 실행/결과 스키마 (계약서 3장)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class AnalyzeAccepted(BaseModel):
    """POST .../extract | .../review | .../analyze 의 202 응답."""

    chapter_no: int
    status: str  # "extracting" | "reviewing"


class ReviewRequest(BaseModel):
    """POST .../review 바디(선택). 없으면 기본값."""

    auto_save: bool = True  # 검수 성공 후 저장(캐논 병합)까지 (D4)


class SpanOut(BaseModel):
    start: int
    end: int
    quote: str = ""


class ConflictRefOut(BaseModel):
    chapter_no: int | None = None
    quote: str | None = None


class ContradictionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    span: SpanOut | None = None
    conflict_ref: ConflictRefOut | None = None
    type: str
    explanation: str | None = None
    confidence: float | None = None
    status: str = "pending"  # pending | confirmed | dismissed (작가 ✓/✕)


class ContradictionStatusUpdate(BaseModel):
    status: str  # pending | confirmed | dismissed


class ResultOut(BaseModel):
    """status에 따라 채워지는 필드가 다름. 라우터에서 exclude_none으로 직렬화.

    - uploaded/extracting/reviewing → {status, progress}
    - extracted                     → {status, highlighted_text, canon_delta}
    - reviewed/saved                → {status, highlighted_text, canon_delta, contradictions}
    - failed                        → {status, detail, failed_stage}
    """

    status: str
    progress: int | None = None
    highlighted_text: str | None = None
    canon_delta: dict | None = None
    contradictions: list[ContradictionItem] | None = None
    detail: str | None = None
    failed_stage: str | None = None


class SaveResult(BaseModel):
    chapter_no: int
    status: str  # "saved"


class VisualOut(BaseModel):
    """회차별 시각화 원본 JSON(LLM prompt_result_1 포맷).

    파이프라인이 rich JSON을 준 회차만 값이 있다(fake 모드 등은 null).
    프론트 시각화 렌더러(DEMO_WORLDVIEW_ROUND1과 동일 구조)가 그대로 소비한다.
    """

    chapter_no: int
    visual: dict | None = None
