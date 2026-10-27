"""몸통 ↔ LLM 파이프라인 경계 (단일 계약 정의).

CLAUDE.md 불변원칙 1: 파이프라인은 이 인터페이스로만 호출한다.
몸통의 일 = CanonSnapshot 구성 → 넘김 → AnalysisOutput.canon_delta 병합.
파이프라인의 일 = 모순 검출 + 구조화(canon_delta 생성). 그 내부는 몸통이 모른다.

입출력 JSON 스키마는 여기 한 곳에서만 정의하고 양쪽이 공유한다.
"""
from __future__ import annotations

import enum
from typing import Annotated, Literal, Protocol, Union

from pydantic import BaseModel, Field, TypeAdapter


# ── 파이프라인 입력: 기존 캐논 스냅샷 ─────────────────────────
class CanonSnapshot(BaseModel):
    """저장된 회차들로부터 구성한 현재 캐논(is_current=true) 스냅샷.

    각 리스트의 항목은 {entity_key, source_chapter, ...내용} 형태의 dict.
    """

    project_id: str
    up_to_chapter: int = 0  # 이 캐논이 반영한 마지막 저장 회차
    worldview: list[dict] = Field(default_factory=list)
    characters: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    spaces: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    foreshadowing: list[dict] = Field(default_factory=list)


# ── 파이프라인 출력: 모순 + 캐논 델타 ─────────────────────────
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
    # setting|character|timeline|space|event|foreshadow
    type: str
    explanation: str = ""
    confidence: float = 0.0


# canon_delta 항목들. 각 항목은 entity_key + 해당 테이블 내용 필드.
#
# attrs(dict)는 복선을 뺀 6종이 공통으로 갖는다: 몸통 컬럼에 자리가 없는 LLM 추출
# 부가 정보(certainty·source_text, 사건 summary/cause/result 등 — transform.py 가 채움).
# 캐논 병합은 attrs 를 비교하되 source_text·certainty 는 빼고 본다(canon_service).
#
# 모든 Delta는 note/quote를 공통으로 갖는다: 1차 추출 결과를 사람이 검토하는
# 단계에서 채워지는 자유 서술(파이프라인이 미리 채워도 되고, 프론트의 "수정하기"가
# PATCH로 채우기도 한다). 캐논 병합(canon_service.CANON_SPECS)은 이 두 필드를 읽지
# 않으므로 canon_* 테이블 스키마에는 영향이 없다 — 2차 검수(review_chapter) 입력용이다.
class WorldviewDelta(BaseModel):
    entity_key: str
    item: str
    detail: str | None = None
    attrs: dict | None = None
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class CharacterDelta(BaseModel):
    entity_key: str
    name: str
    group_name: str | None = None
    attrs: dict | None = None
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class RelationDelta(BaseModel):
    entity_key: str
    from_char: str  # 인물 entity_key
    to_char: str
    relation: str | None = None
    attrs: dict | None = None
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class TimelineDelta(BaseModel):
    entity_key: str
    scene_label: str | None = None
    order_index: int = 0
    time_value: str | None = None
    attrs: dict | None = None
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class SpaceDelta(BaseModel):
    entity_key: str
    scene_label: str | None = None
    place: str | None = None
    attrs: dict | None = None
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class EventDelta(BaseModel):
    entity_key: str
    label: str
    stage: str | None = None
    order_index: int = 0
    attrs: dict | None = None
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class ForeshadowingDelta(BaseModel):
    entity_key: str
    label: str
    parent_key: str | None = None
    kind: str | None = None  # setup|payoff
    note: str | None = None   # 1차 검토 자유 서술 (위 주석 참조)
    quote: str | None = None  # 근거 원문 인용


class CanonDelta(BaseModel):
    worldview: list[WorldviewDelta] = Field(default_factory=list)
    characters: list[CharacterDelta] = Field(default_factory=list)
    relations: list[RelationDelta] = Field(default_factory=list)
    timeline: list[TimelineDelta] = Field(default_factory=list)
    spaces: list[SpaceDelta] = Field(default_factory=list)
    events: list[EventDelta] = Field(default_factory=list)
    foreshadowing: list[ForeshadowingDelta] = Field(default_factory=list)


# 카테고리 이름 → Delta 모델. 추출 결과 항목 편집 API에서 category별 검증/직렬화에 재사용.
# canon_delta JSON의 키와 정확히 일치한다. 각 항목의 정체성은 entity_key.
CATEGORY_MODELS: dict[str, type[BaseModel]] = {
    "worldview": WorldviewDelta,
    "characters": CharacterDelta,
    "relations": RelationDelta,
    "timeline": TimelineDelta,
    "spaces": SpaceDelta,
    "events": EventDelta,
    "foreshadowing": ForeshadowingDelta,
}


# 1차 추출 결과: 6기준 구조화 데이터(canon_delta) 중심. 모순 판정은 하지 않는다.
class ExtractionOutput(BaseModel):
    highlighted_text: str = ""
    canon_delta: CanonDelta = Field(default_factory=CanonDelta)
    # LLM이 준 원본 시각화 JSON(prompt_result_1 포맷). 있으면 몸통이
    # analysis_results.raw_output에 회차별로 보존해 시각화 API로 내려준다.
    visual_json: dict | None = None


# 2차 검수 결과: 기존 캐논 + (사용자 확정) 추출 데이터 대조로 나온 모순 목록.
class ReviewOutput(BaseModel):
    contradictions: list[ContradictionOut] = Field(default_factory=list)


# ── 2차 검수 스트림 이벤트 (초안 — AI 파트 합의 전) ──────────────
# /review 는 임베딩 → 모순 탐지를 한 요청 안에서 처리하고, 응답을 한 번에 주는
# 대신 NDJSON(Content-Type: application/x-ndjson, 한 줄 = JSON 이벤트 1개)으로
# 진행 상황을 흘려보낸다. 몸통 워커는 이벤트가 올 때마다 DB에 단계를 기록한다.
# AI 서버가 몸통을 역호출(콜백)하지 않으므로 stateless·요청-응답 구조가 유지된다.
#
# 규칙
#   1. 정상 흐름:  embedding_done → result   (각 1회, 이 순서)
#   2. 실패 흐름:  (embedding_done →) error  — error 는 마지막 줄. 이후 아무것도 보내지 않는다.
#   3. result 또는 error 로 끝나지 않고 스트림이 닫히면 몸통은 실패로 처리한다.
#   4. 스트림 시작 전 오류(입력 검증 실패 등)는 지금처럼 HTTP 4xx/5xx 로 응답한다.
#      스트림이 시작된 뒤(HTTP 200 이후)의 오류는 반드시 error 이벤트로 알린다.
#   5. 이벤트마다 즉시 flush 한다(버퍼링되면 몸통이 단계를 늦게 안다).
#   6. 모르는 event 값은 보내지 않는다 — 새 이벤트는 여기에 먼저 추가하고 합의한다.
#
# 예)
#   {"event": "embedding_done"}
#   {"event": "result", "contradictions": [...]}
class ReviewStage(str, enum.Enum):
    """2차 검수 안의 세부 단계. chapters.status == reviewing 일 때만 의미가 있다."""

    embedding = "embedding"  # 임베딩 중 (요청 시작 ~ embedding_done)
    detecting = "detecting"  # 모순 탐지 중 (embedding_done ~ result)


class EmbeddingDoneEvent(BaseModel):
    """임베딩 완료 → 몸통은 단계를 embedding → detecting 으로 기록."""

    event: Literal["embedding_done"] = "embedding_done"


class ReviewResultEvent(ReviewOutput):
    """최종 결과. 필드는 ReviewOutput 과 동일(+event)."""

    event: Literal["result"] = "result"


class ReviewErrorEvent(BaseModel):
    """스트림 도중 실패. stage 로 어느 단계에서 실패했는지 알린다."""

    event: Literal["error"] = "error"
    stage: ReviewStage
    message: str = ""


ReviewEvent = Annotated[
    Union[EmbeddingDoneEvent, ReviewResultEvent, ReviewErrorEvent],
    Field(discriminator="event"),
]
REVIEW_EVENT_ADAPTER: TypeAdapter[ReviewEvent] = TypeAdapter(ReviewEvent)


def parse_review_event(line: str | bytes) -> ReviewEvent:
    """NDJSON 한 줄 → 이벤트 모델. 형식이 틀리면 pydantic.ValidationError."""
    return REVIEW_EVENT_ADAPTER.validate_json(line)


# ── 연결 사전 점검 ──────────────────────────────────────────
class PipelineHealth(BaseModel):
    """분석 시작 전 사전 점검 결과.

    연결이 안 돼도 예외를 던지지 않고 ok=False + message 로 돌려준다 —
    호출하는 쪽(프론트)이 업로드 전에 원인을 보여주고 멈추는 용도라서.
    """

    ok: bool
    mode: str  # fake | remote | local
    message: str = ""  # 사용자에게 보여줄 한 줄 (실패 시 원인)
    info: dict = Field(default_factory=dict)  # 구현체가 준 부가 정보 (AI 서버 /health 응답 등)


# ── 계약 (2단계: 추출 → 검수) ──────────────────────────────
class AnalysisPipeline(Protocol):
    async def health(self) -> PipelineHealth:
        """연결 사전 점검. LLM 을 호출하지 않고 수 초 안에 끝나야 한다."""
        ...

    async def extract_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ExtractionOutput:
        """1차 추출: 회차 원문에서 6기준 구조화 데이터(canon_delta)를 뽑는다.

        이 단계는 모순을 판정하지 않는다(검수는 review_chapter). 캐논은 건드리지 않는다.
        title이 "[규칙]"으로 시작하면 사용자가 올린 설정/규칙 문서다 — 서사가 아니므로
        본문을 명시적 세계관 규칙으로 취급해야 한다.
        chapter_no는 이번 회차 번호. 파이프라인이 회차별 내부 상태(ID 통합·임베딩)를
        쌓을 때 쓴다. canon.up_to_chapter(마지막 저장 회차)와는 다르다.
        """
        ...

    async def review_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        delta: CanonDelta,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ReviewOutput:
        """2차 검수: 기존 캐논 + (확정된) 추출 데이터(delta)를 대조해 모순을 반환한다."""
        ...
