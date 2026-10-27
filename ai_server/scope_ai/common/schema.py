"""Scope JSON 최상위 스키마 관련 상수/검증."""

from __future__ import annotations

from typing import Any


EP_FIELDS = (
    "worldview_rules",
    "characters",
    "events",
    "times",
    "locations",
)


def empty_ep() -> dict[str, list[dict]]:
    return {field: [] for field in EP_FIELDS}


def validate_ep(data: Any) -> None:
    if not isinstance(data, dict):
        raise ValueError("ep JSON의 최상위 구조는 객체여야 합니다.")

    missing = [field for field in EP_FIELDS if field not in data]
    if missing:
        raise ValueError(f"ep JSON 필드 누락: {', '.join(missing)}")

    for field in EP_FIELDS:
        if not isinstance(data[field], list):
            raise ValueError(f"ep JSON의 '{field}'는 배열이어야 합니다.")
