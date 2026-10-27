"""몸통(app/pipeline/interface.py)과 공유하는 경계 스키마.

여기 정의는 몸통의 CanonSnapshot / ExtractionOutput / ReviewOutput 을
그대로 미러한 것이다. 몸통 쪽 interface.py 가 바뀌면 이 파일도 같이 바꾼다.
필드를 임의로 추가/삭제하지 말 것 — 계약이다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── 요청 ────────────────────────────────────────────────
class CanonSnapshot(BaseModel):
    """몸통이 보내주는 '이전 회차까지 누적된 캐논' 스냅샷."""

    project_id: str = ""
    up_to_chapter: int = 0
    worldview: list[dict] = Field(default_factory=list)
    characters: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    spaces: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    foreshadowing: list[dict] = Field(default_factory=list)

    def total_items(self) -> int:
        return sum(
            len(getattr(self, name))
            for name in (
                "worldview",
                "characters",
                "relations",
                "timeline",
                "spaces",
                "events",
                "foreshadowing",
            )
        )


class ExtractRequest(BaseModel):
    """POST /extract 요청 본문 (remote.py 가 보내는 그대로)."""

    chapter_text: str
    canon: CanonSnapshot = Field(default_factory=CanonSnapshot)
    title: str | None = None
    # 이번 회차 번호. scope_ai 가 회차별 상태(ID 통합·임베딩)를 쌓는 키다.
    # 구버전 몸통처럼 안 보내면 canon.up_to_chapter + 1 로 추정한다.
    chapter_no: int | None = None


class ReviewRequest(ExtractRequest):
    """POST /review 요청 본문. 사용자가 확정한 이번 회차 델타가 추가로 온다."""

    delta: dict = Field(default_factory=dict)


# ── 응답 ────────────────────────────────────────────────
# /extract 는 prompt_result_1 rich JSON(dict)을 그대로 돌려준다.
# 몸통 remote.py 의 looks_like_visual_json() 이 잡아서 CanonDelta 로 변환하고
# 원본은 raw_output 에 보존한다 → GET /visual 로 프론트 시각화에 내려간다.
# 따라서 여기서 응답 모델을 강제하지 않는다(정보 손실 방지).


class Span(BaseModel):
    start: int
    end: int
    quote: str = ""


class ConflictRef(BaseModel):
    chapter_no: int | None = None
    quote: str | None = None


class ContradictionOut(BaseModel):
    span: Span
    conflict_ref: ConflictRef
    # setting | character | timeline | space | event | foreshadow
    type: str
    explanation: str = ""
    confidence: float = 0.0


class ReviewResponse(BaseModel):
    """POST /review 응답. 몸통이 ReviewOutput.model_validate() 로 바로 검증하므로
    이 스키마에서 한 글자라도 어긋나면 422 가 아니라 몸통에서 터진다."""

    contradictions: list[ContradictionOut] = Field(default_factory=list)
