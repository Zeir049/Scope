"""Character ID 계획 및 누적 병합."""

from __future__ import annotations

from copy import deepcopy

from .id_utils import next_id_number


def _norm(value: str | None) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def character_names(character: dict) -> set[str]:
    names = set()
    if _norm(character.get("name")):
        names.add(_norm(character.get("name")))
    aliases = character.get("aliases", [])
    if isinstance(aliases, list):
        names.update(_norm(v) for v in aliases if _norm(v))
    return names


def find_existing(new_character: dict, existing: list[dict]) -> dict | None:
    candidates = character_names(new_character)
    if not candidates:
        return None
    for character in existing:
        if candidates & character_names(character):
            return character
    return None


def plan_character_ids(new_items: list[dict], existing: list[dict]) -> dict[str, str]:
    number = next_id_number(existing, "character_id", "CHAR")
    mapping: dict[str, str] = {}
    provisional_existing = deepcopy(existing)

    for item in new_items:
        local_id = item.get("character_id")
        if not local_id:
            raise ValueError("character_id가 없는 캐릭터가 있습니다.")

        matched = find_existing(item, provisional_existing)
        if matched:
            mapping[local_id] = matched["character_id"]
            continue

        global_id = f"CHAR_{number:03d}"
        number += 1
        mapping[local_id] = global_id

        shadow = deepcopy(item)
        shadow["character_id"] = global_id
        provisional_existing.append(shadow)

    return mapping


def _merge_aliases(target: dict, incoming: dict) -> None:
    primary = _norm(target.get("name"))
    values: dict[str, str] = {}

    for alias in target.get("aliases", []) if isinstance(target.get("aliases"), list) else []:
        if _norm(alias) and _norm(alias) != primary:
            values.setdefault(_norm(alias), alias.strip())

    incoming_name = incoming.get("name")
    if _norm(incoming_name) and _norm(incoming_name) != primary:
        values.setdefault(_norm(incoming_name), incoming_name.strip())

    for alias in incoming.get("aliases", []) if isinstance(incoming.get("aliases"), list) else []:
        if _norm(alias) and _norm(alias) != primary:
            values.setdefault(_norm(alias), alias.strip())

    target["aliases"] = list(values.values())


def merge_characters(
    transformed_items: list[dict],
    existing: list[dict],
    submission_number: int,
) -> list[dict]:
    result = deepcopy(existing)
    by_id = {item.get("character_id"): item for item in result}

    for item in transformed_items:
        global_id = item["character_id"]
        current = by_id.get(global_id)
        if current is None:
            copied = deepcopy(item)
            copied["source_submissions"] = [submission_number]
            copied.setdefault("aliases", [])
            result.append(copied)
            by_id[global_id] = copied
            continue

        _merge_aliases(current, item)
        sources = current.get("source_submissions", [])
        if not isinstance(sources, list):
            sources = []
        if submission_number not in sources:
            sources.append(submission_number)
            sources.sort()
        current["source_submissions"] = sources

        # TODO: 동일 캐릭터의 상태/관계/목표 변화 병합 정책은 추후 확정 필요.
        # 현재는 기존 대표 데이터를 보존하고 aliases/source_submissions만 누적한다.

    return result
