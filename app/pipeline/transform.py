"""LLM 시각화 JSON(prompt_result_1 포맷) → CanonDelta 변환.

LLM 파이프라인은 회차 분석 결과를 시각화 친화적인 rich JSON
(worldview_rules / characters / events / times / locations, 각 항목에
source_text·certainty 포함)으로 내려준다. 몸통(캐논 병합·모순 대조)은
CanonDelta 스키마를 쓰므로 여기서 단방향 변환한다.

몸통 컬럼에 자리가 없는 정보는 버리지 않고 각 항목의 attrs(dict)에 담는다 —
시각화 화면이 원본 JSON 대신 캐논(및 저장 전엔 canon_delta)만으로 그려질 수 있어야
해서다. attrs 의 키는 원본 포맷의 이름을 그대로 쓴다.

  공통   : certainty, source_text
  세계관 : (없음 — description 은 detail 컬럼)
  인물   : description, aliases, traits=[{trait, trait_type, certainty}], first_appearance_event_id
  관계   : relationship_type, sentiment, description
  사건   : summary, cause, result, main_actor_character_id, participant_character_ids
  시간   : description
  공간   : description

비어 있는 값(None·""·[])은 넣지 않고, 담을 게 없으면 attrs=None.
캐논 병합은 attrs 중 source_text·certainty 를 비교에서 뺀다(canon_service).

entity_key는 LLM이 준 안정적 ID(rule_id/character_id/...)를 그대로 써서
같은 회차를 재분석해도 캐논 병합이 멱등이 되게 한다.
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.pipeline.interface import (
    CanonDelta,
    CharacterDelta,
    EventDelta,
    RelationDelta,
    SpaceDelta,
    TimelineDelta,
    WorldviewDelta,
)

# rich JSON을 식별하는 최상위 키 (하나라도 있으면 시각화 포맷으로 간주)
_VISUAL_KEYS = ("worldview_rules", "characters", "events", "times", "locations")

# 모든 항목이 공통으로 갖는 부가 정보
_COMMON_ATTRS = ("certainty", "source_text")


def looks_like_visual_json(data: dict) -> bool:
    """페이로드가 prompt_result_1 포맷(rich JSON)인지 판별한다."""
    return isinstance(data, dict) and any(k in data for k in _VISUAL_KEYS)


def _key(prefix: str, given: str | None, fallback_text: str) -> str:
    """LLM이 준 ID를 우선 쓰고, 없으면 내용 해시로 안정적 키를 만든다."""
    if given:
        return given
    digest = hashlib.sha1(fallback_text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _present(value: Any) -> bool:
    """attrs 에 담을 가치가 있는 값인가 (None·빈 문자열·빈 리스트 제외)."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict)) and not value:
        return False
    return True


def _attrs(src: dict, keys: tuple[str, ...], **extra: Any) -> dict | None:
    """src 에서 keys(+공통 키)를 골라 attrs dict 를 만든다. 비면 None."""
    out: dict = {}
    for k in keys + _COMMON_ATTRS:
        if _present(src.get(k)):
            out[k] = src[k]
    for k, v in extra.items():
        if _present(v):
            out[k] = v
    return out or None


def _traits(raw: list | None) -> list[dict]:
    """traits → [{trait, trait_type, certainty}] (키 3개 고정, 없으면 None)."""
    return [
        {
            "trait": t["trait"],
            "trait_type": t.get("trait_type"),
            "certainty": t.get("certainty"),
        }
        for t in raw or []
        if isinstance(t, dict) and t.get("trait")
    ]


def visual_to_canon_delta(visual: dict) -> CanonDelta:
    """rich JSON → CanonDelta. 몸통 컬럼에 맞는 필드는 컬럼으로, 나머지는 attrs 로."""
    worldview = [
        WorldviewDelta(
            entity_key=_key("rule", r.get("rule_id"), r.get("content", "")),
            item=r.get("content", ""),
            detail=r.get("description"),
            attrs=_attrs(r, ()),
        )
        for r in visual.get("worldview_rules", [])
        if r.get("content")
    ]

    characters: list[CharacterDelta] = []
    relations: list[RelationDelta] = []
    for c in visual.get("characters", []):
        if not c.get("name"):
            continue
        char_key = _key("char", c.get("character_id"), c["name"])
        characters.append(
            CharacterDelta(
                entity_key=char_key,
                name=c["name"],
                attrs=_attrs(
                    c,
                    ("description", "aliases", "first_appearance_event_id"),
                    traits=_traits(c.get("traits")),
                ),
            )
        )
        for rel in c.get("relationships", []):
            target = rel.get("target_character_id")
            if not target:
                continue
            relations.append(
                RelationDelta(
                    entity_key=f"{char_key}->{target}",
                    from_char=char_key,
                    to_char=target,
                    relation=rel.get("relationship_type") or rel.get("description"),
                    attrs=_attrs(rel, ("relationship_type", "sentiment", "description")),
                )
            )

    events = [
        EventDelta(
            entity_key=_key("event", e.get("event_id"), e.get("title", "")),
            label=e.get("title", ""),
            order_index=e.get("order", i + 1),
            attrs=_attrs(
                e,
                (
                    "summary",
                    "cause",
                    "result",
                    "main_actor_character_id",
                    "participant_character_ids",
                ),
            ),
        )
        for i, e in enumerate(visual.get("events", []))
        if e.get("title")
    ]

    timeline = [
        TimelineDelta(
            entity_key=_key("time", t.get("time_id"), t.get("expression", "")),
            time_value=t.get("expression"),
            order_index=i + 1,
            attrs=_attrs(t, ("description",)),
        )
        for i, t in enumerate(visual.get("times", []))
        if t.get("expression")
    ]

    spaces = [
        SpaceDelta(
            entity_key=_key("loc", s.get("location_id"), s.get("name", "")),
            place=s.get("name"),
            attrs=_attrs(s, ("description",)),
        )
        for s in visual.get("locations", [])
        if s.get("name")
    ]

    return CanonDelta(
        worldview=worldview,
        characters=characters,
        relations=relations,
        events=events,
        timeline=timeline,
        spaces=spaces,
    )
