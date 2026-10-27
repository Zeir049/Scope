"""캐논 회차 기여 조회(chapter=N) + 응답 attrs.

chapter=N 은 N화가 캐논에 넣은 행 전부(이후 대체된 버전 포함)를 준다 — 회차별 시각화가
LLM 원본 JSON 대신 캐논을 읽기 위한 것. at_chapter(시점 조회)와 함께 주면 400.
"""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.test_canon_at_chapter import KEY, _canon, _register, _save_chapter


async def _by_chapter(client: AsyncClient, pid: str, h: dict, view: str, n: int) -> dict:
    r = await client.get(
        f"/projects/{pid}/canon", params={"view": view, "chapter": n}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_chapter_returns_rows_sourced_in_that_chapter_including_superseded(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    res1 = await _save_chapter(client, pid, h, 1, edit_item=None)
    original = next(x["item"] for x in res1["canon_delta"]["worldview"] if x["entity_key"] == KEY)
    await _save_chapter(client, pid, h, 2, edit_item="2화에서 바뀐 규칙")

    # 1화: 모든 규칙이 1화 출처. RULE_001 v1 은 2화에서 대체됐지만 그대로 보인다.
    ch1 = await _by_chapter(client, pid, h, "worldview", 1)
    assert ch1["items"] and all(it["source_chapter"] == 1 for it in ch1["items"])
    rule = next(it for it in ch1["items"] if it["entity_key"] == KEY)
    assert rule["item"] == original and rule["version"] == 1
    assert rule["is_current"] is False and rule["superseded_at_chapter"] == 2
    # 대체되지 않은 다른 규칙은 현재 버전
    other = next(it for it in ch1["items"] if it["entity_key"] != KEY)
    assert other["is_current"] is True and other["superseded_at_chapter"] is None

    # 2화: 2화가 넣은 행 = 바뀐 RULE_001 v2 하나뿐 (나머지는 1화와 같아 unchanged)
    ch2 = await _by_chapter(client, pid, h, "worldview", 2)
    assert [(it["entity_key"], it["version"], it["item"]) for it in ch2["items"]] == [
        (KEY, 2, "2화에서 바뀐 규칙")
    ]
    assert ch2["items"][0]["is_current"] is True

    # 시점 조회(at_chapter)와 다르다: at_chapter=2 는 항목당 1행(현재 유효 버전)
    at2 = await _canon(client, pid, h, "worldview", 2)
    assert len(at2["items"]) == len(ch1["items"])

    # 기여 없는 회차 → 빈 목록
    assert (await _by_chapter(client, pid, h, "worldview", 7))["items"] == []


async def test_chapter_items_carry_attrs_on_every_view(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _save_chapter(client, pid, h, 1, edit_item=None)

    wv = await _by_chapter(client, pid, h, "worldview", 1)
    assert all(it["attrs"]["source_text"] and it["attrs"]["certainty"] for it in wv["items"])

    chars = await _by_chapter(client, pid, h, "characters", 1)
    klein = next(n for n in chars["nodes"] if n["entity_key"] == "CHAR_001")
    assert klein["attrs"]["traits"][0]["trait"] and klein["attrs"]["traits"][0]["trait_type"]
    assert klein["attrs"]["source_text"]
    edge = next(e for e in chars["edges"] if e["entity_key"] == "CHAR_002->CHAR_004")
    assert edge["attrs"]["sentiment"] == "negative" and edge["attrs"]["relationship_type"] == "family"
    assert edge["source_chapter"] == 1 and edge["is_current"] is True

    ev = await _by_chapter(client, pid, h, "events", 1)
    first = next(it for it in ev["items"] if it["entity_key"] == "EVENT_001")
    assert first["attrs"]["summary"] and first["attrs"]["cause"] and first["attrs"]["result"]
    assert first["attrs"]["participant_character_ids"] == ["CHAR_003", "CHAR_005"]
    assert first["attrs"]["main_actor_character_id"] == "CHAR_005"

    tl = await _by_chapter(client, pid, h, "timeline", 1)
    assert all(it["attrs"]["description"] for it in tl["items"])

    sp = await _by_chapter(client, pid, h, "spaces", 1)
    assert all(it["attrs"]["description"] for it in sp["items"])

    # 현재 캐논 조회도 같은 키를 갖는다 (attrs + 버전 메타)
    for view in ("worldview", "timeline", "spaces", "events"):
        for it in (await _canon(client, pid, h, view))["items"]:
            assert "attrs" in it and "version" in it and "is_current" in it and "superseded_at_chapter" in it
    for it in (await _canon(client, pid, h, "foreshadowing"))["items"]:
        assert "attrs" not in it and "superseded_at_chapter" in it


async def test_chapter_param_validation_and_ownership(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    r = await client.get(
        f"/projects/{pid}/canon", params={"view": "worldview", "chapter": 1, "at_chapter": 1}, headers=h
    )
    assert r.status_code == 400 and "함께" in r.json()["detail"]
    r = await client.get(f"/projects/{pid}/canon", params={"view": "worldview", "chapter": 0}, headers=h)
    assert r.status_code == 400
    r = await client.get(f"/projects/{pid}/canon", params={"view": "bogus", "chapter": 1}, headers=h)
    assert r.status_code == 400

    other = await _register(client)
    r = await client.get(f"/projects/{pid}/canon", params={"view": "worldview", "chapter": 1}, headers=other)
    assert r.status_code == 403
    r = await client.get(
        f"/projects/{uuid.uuid4()}/canon", params={"view": "worldview", "chapter": 1}, headers=h
    )
    assert r.status_code == 404
