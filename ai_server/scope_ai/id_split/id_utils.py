"""ID 생성/비교 공통 유틸리티."""

from __future__ import annotations

import re


def next_id_number(items: list[dict], id_field: str, prefix: str) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    max_number = 0
    for item in items:
        value = item.get(id_field)
        if not isinstance(value, str):
            continue
        match = pattern.match(value)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return max_number + 1


def sequential_id_map(
    new_items: list[dict],
    existing_items: list[dict],
    *,
    id_field: str,
    prefix: str,
) -> dict[str, str]:
    number = next_id_number(existing_items, id_field, prefix)
    result: dict[str, str] = {}
    for item in new_items:
        local_id = item.get(id_field)
        if not local_id:
            raise ValueError(f"{id_field}가 없는 데이터가 있습니다.")
        if local_id in result:
            raise ValueError(f"한 ep 안에서 ID가 중복되었습니다: {local_id}")
        result[local_id] = f"{prefix}_{number:03d}"
        number += 1
    return result
