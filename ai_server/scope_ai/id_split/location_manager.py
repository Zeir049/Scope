from __future__ import annotations
from copy import deepcopy
from .id_utils import sequential_id_map


def plan_location_ids(new_items: list[dict], existing: list[dict]) -> dict[str, str]:
    return sequential_id_map(new_items, existing, id_field="location_id", prefix="LOCATION")


def merge_locations(transformed_items: list[dict], existing: list[dict], submission_number: int) -> list[dict]:
    result = deepcopy(existing)
    for item in transformed_items:
        copied = deepcopy(item)
        copied["source_submission"] = submission_number
        result.append(copied)
    return result
