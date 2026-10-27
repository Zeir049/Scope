"""ep 내부 local ID를 작품 전체 global ID로 재귀 치환."""

from __future__ import annotations

from typing import Any


def replace_references(value: Any, mappings: list[dict[str, str]]) -> Any:
    if isinstance(value, str):
        for mapping in mappings:
            if value in mapping:
                return mapping[value]
        return value
    if isinstance(value, list):
        return [replace_references(v, mappings) for v in value]
    if isinstance(value, dict):
        return {k: replace_references(v, mappings) for k, v in value.items()}
    return value
