"""2차 검수 스트림 이벤트 계약(interface.py) 파싱 테스트."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.pipeline.interface import (
    EmbeddingDoneEvent,
    ReviewErrorEvent,
    ReviewResultEvent,
    ReviewStage,
    parse_review_event,
)


def test_embedding_done() -> None:
    ev = parse_review_event('{"event": "embedding_done"}')
    assert isinstance(ev, EmbeddingDoneEvent)


def test_result_carries_contradictions() -> None:
    line = (
        '{"event": "result", "contradictions": [{"span": {"start": 0, "end": 3, "quote": "abc"},'
        ' "conflict_ref": {"chapter_no": 1, "quote": "x"}, "type": "character",'
        ' "explanation": "e", "confidence": 0.8}]}'
    )
    ev = parse_review_event(line)
    assert isinstance(ev, ReviewResultEvent)
    assert len(ev.contradictions) == 1
    assert ev.contradictions[0].type == "character"


def test_result_empty_is_valid() -> None:
    ev = parse_review_event(b'{"event": "result"}')
    assert isinstance(ev, ReviewResultEvent)
    assert ev.contradictions == []


def test_error_has_stage() -> None:
    ev = parse_review_event('{"event": "error", "stage": "embedding", "message": "oom"}')
    assert isinstance(ev, ReviewErrorEvent)
    assert ev.stage is ReviewStage.embedding


@pytest.mark.parametrize(
    "line",
    [
        '{"event": "progress"}',                       # 합의되지 않은 이벤트
        '{"event": "error", "stage": "extracting"}',   # 없는 단계
        '{"contradictions": []}',                      # event 누락
        "not json",
    ],
)
def test_invalid_lines_rejected(line: str) -> None:
    with pytest.raises(ValidationError):
        parse_review_event(line)
