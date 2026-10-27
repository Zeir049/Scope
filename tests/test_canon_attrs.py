"""캐논 attrs 보존(0005) 테스트.

- transform: rich JSON 의 certainty·source_text·사건/관계/시간 상세가 attrs 에 남는지
- normalize_for_compare: source_text·certainty(중첩 포함)만 빼고 본다
- 병합: 같은 내용 + 다른 source_text → 버전 안 쌓임 / description 바뀜 → 버전 쌓이고 is_current 1개
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import CanonEvent, CanonTimeline, Project
from app.pipeline.transform import visual_to_canon_delta
from app.repository.user_repo import UserRepository
from app.service.canon_service import CanonService, normalize_for_compare

FAKE_VISUAL: dict = json.loads(
    (Path("app/pipeline/fake_visual.json")).read_text(encoding="utf-8")
)


# ── transform ─────────────────────────────────────────────────
def test_transform_keeps_certainty_and_source_text_everywhere():
    d = visual_to_canon_delta(FAKE_VISUAL)
    for items in (d.worldview, d.characters, d.relations, d.events, d.timeline, d.spaces):
        assert items
        for it in items:
            assert it.attrs and it.attrs["certainty"] and it.attrs["source_text"], it.entity_key


def test_transform_keeps_category_details():
    d = visual_to_canon_delta(FAKE_VISUAL)

    klein = next(c for c in d.characters if c.entity_key == "CHAR_001")
    assert klein.attrs["description"].startswith("헤일트라움의 운영자")
    assert klein.attrs["aliases"] == ["클라인 브루더", "Klein Bruder"]
    assert klein.attrs["first_appearance_event_id"] == "EVENT_003"
    assert klein.attrs["traits"][0] == {
        "trait": "30대 초반의 외모", "trait_type": "appearance", "certainty": "explicit"
    }
    assert all(set(t) == {"trait", "trait_type", "certainty"} for t in klein.attrs["traits"])

    rel = next(r for r in d.relations if r.entity_key == "CHAR_002->CHAR_004")
    assert rel.relation == "family"
    assert rel.attrs["relationship_type"] == "family"
    assert rel.attrs["sentiment"] == "negative"
    assert rel.attrs["description"].startswith("어머니가")

    ev = next(e for e in d.events if e.entity_key == "EVENT_001")
    assert ev.attrs["summary"] and ev.attrs["cause"] and ev.attrs["result"]
    assert ev.attrs["main_actor_character_id"] == "CHAR_005"
    assert ev.attrs["participant_character_ids"] == ["CHAR_003", "CHAR_005"]

    tl = next(t for t in d.timeline if t.entity_key == "TIME_002")
    assert tl.time_value == "목요일 점심 전"
    assert tl.attrs["description"] == "악몽에서 깬 후 점심시간 전 시점"

    sp = next(s for s in d.spaces if s.entity_key == "LOC_001")
    assert sp.attrs["description"].startswith("창문이 없고")

    # 세계관은 공통 키만 (description 은 detail 컬럼)
    wv = next(w for w in d.worldview if w.entity_key == "RULE_001")
    assert set(wv.attrs) == {"certainty", "source_text"}


def test_transform_omits_empty_values():
    d = visual_to_canon_delta(
        {
            "characters": [{"character_id": "C", "name": "무명", "aliases": [], "traits": [], "description": ""}],
            "events": [{"event_id": "E", "title": "일", "participant_character_ids": []}],
        }
    )
    assert d.characters[0].attrs is None
    assert d.events[0].attrs is None


# ── normalize_for_compare ──────────────────────────────────────
def test_normalize_strips_source_text_and_certainty_recursively():
    a = {
        "name": "클라인",
        "group_name": None,
        "attrs": {
            "description": "가이드",
            "source_text": "원문 A",
            "certainty": "explicit",
            "traits": [{"trait": "단정한 말투", "trait_type": "personality", "certainty": "inferred"}],
        },
    }
    b = {
        "name": "클라인",
        "group_name": None,
        "attrs": {
            "description": "가이드",
            "source_text": "원문 B",
            "certainty": "uncertain",
            "traits": [{"trait": "단정한 말투", "trait_type": "personality", "certainty": "explicit"}],
        },
    }
    assert normalize_for_compare(a) == normalize_for_compare(b)
    assert normalize_for_compare(a)["attrs"] == {
        "description": "가이드",
        "traits": [{"trait": "단정한 말투", "trait_type": "personality"}],
    }
    # 비교 전용 — 입력은 그대로
    assert a["attrs"]["source_text"] == "원문 A"


@pytest.mark.parametrize(
    "attrs",
    [None, {}, {"source_text": "x"}, {"certainty": "explicit", "source_text": "y"}],
)
def test_normalize_treats_empty_attrs_as_none(attrs):
    assert normalize_for_compare({"item": "a", "attrs": attrs}) == {"item": "a", "attrs": None}


def test_normalize_sees_real_changes():
    base = {"label": "회의", "attrs": {"summary": "s1", "source_text": "q"}}
    changed = {"label": "회의", "attrs": {"summary": "s2", "source_text": "q"}}
    assert normalize_for_compare(base) != normalize_for_compare(changed)
    assert normalize_for_compare({"label": "회의", "attrs": None}) != normalize_for_compare(base)


# ── 병합 (서비스) ─────────────────────────────────────────────
async def _project() -> tuple[object, uuid.UUID]:
    s = SessionLocal()
    user = await UserRepository(s).create(
        f"ca_{uuid.uuid4().hex[:8]}@x.com", hash_password("x"), "t"
    )
    project = Project(owner_id=user.id, name="canon-attrs")
    s.add(project)
    await s.flush()
    return s, project.id


async def _rows(s, model, pid, key):
    res = await s.execute(
        select(model).where(model.project_id == pid, model.entity_key == key).order_by(model.version)
    )
    return list(res.scalars().all())


def _time(desc: str, src: str, cert: str = "explicit") -> dict:
    return {
        "entity_key": "TIME_001",
        "time_value": "목요일",
        "order_index": 1,
        "attrs": {"description": desc, "source_text": src, "certainty": cert},
    }


async def test_merge_same_content_different_source_text_is_unchanged():
    s, pid = await _project()
    async with s:
        cs = CanonService(s)
        st1 = await cs.merge_delta(pid, {"timeline": [_time("강의 없는 날", "원문 1")]}, 1)
        st2 = await cs.merge_delta(pid, {"timeline": [_time("강의 없는 날", "원문 2", "inferred")]}, 2)
        await s.commit()
        rows = await _rows(s, CanonTimeline, pid, "TIME_001")

    assert st1["inserted"] == 1 and st2["unchanged"] == 1 and st2["versioned"] == 0
    assert len(rows) == 1 and rows[0].is_current and rows[0].version == 1
    # 저장된 값은 첫 버전 그대로(출처 인용도 보관)
    assert rows[0].attrs["source_text"] == "원문 1"


async def test_merge_description_change_creates_version_with_single_current():
    s, pid = await _project()
    async with s:
        cs = CanonService(s)
        await cs.merge_delta(pid, {"timeline": [_time("강의 없는 날", "원문 1")]}, 1)
        st = await cs.merge_delta(pid, {"timeline": [_time("게임을 시작한 날", "원문 1")]}, 2)
        await s.commit()
        rows = await _rows(s, CanonTimeline, pid, "TIME_001")

    assert st["versioned"] == 1
    assert [r.version for r in rows] == [1, 2]
    assert [r.is_current for r in rows] == [False, True]
    assert rows[0].superseded_at_chapter == 2 and rows[0].superseded_by == rows[1].id
    assert rows[1].attrs["description"] == "게임을 시작한 날"


async def test_merge_event_attrs_round_trip_and_null_to_value_is_change():
    """attrs 가 없던 행(0005 이전 저장분처럼)에 내용이 생기면 새 버전이다."""
    s, pid = await _project()
    async with s:
        cs = CanonService(s)
        await cs.merge_delta(pid, {"events": [{"entity_key": "EVENT_001", "label": "회의", "order_index": 1}]}, 1)
        st = await cs.merge_delta(
            pid,
            {"events": [{"entity_key": "EVENT_001", "label": "회의", "order_index": 1,
                          "attrs": {"summary": "정책 논쟁", "participant_character_ids": ["CHAR_003"], "source_text": "q"}}]},
            2,
        )
        # 출처만 있는 attrs 는 None 과 같다 → 버전 안 쌓임
        st3 = await cs.merge_delta(
            pid,
            {"events": [{"entity_key": "EVENT_002", "label": "꿈", "order_index": 2, "attrs": {"source_text": "q"}}]},
            2,
        )
        await s.commit()
        rows = await _rows(s, CanonEvent, pid, "EVENT_001")
        rows2 = await _rows(s, CanonEvent, pid, "EVENT_002")

    assert st["versioned"] == 1 and len(rows) == 2
    assert rows[1].attrs == {"summary": "정책 논쟁", "participant_character_ids": ["CHAR_003"], "source_text": "q"}
    assert st3["inserted"] == 1 and len(rows2) == 1
