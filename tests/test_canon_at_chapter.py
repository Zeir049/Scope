"""캐논 시점 조회(at_chapter) + entity_key/attrs 보강.

- API: FakePipeline 으로 1→2→3화를 저장하면서 2·3화에서 같은 세계관 항목을 편집해
  버전 체인(v1→v2→v3)을 만들고, at_chapter=1/2/3 이 각 시점의 내용인지 본다.
- 서비스: 철회(retire)된 행은 빠지고, 복원(restore)된 행은 다시 잡히는지 본다.
"""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Project
from app.repository.user_repo import UserRepository
from app.service.canon_service import CanonService
from tests.util import MANUAL_SAVE, poll_result

KEY = "RULE_001"  # FakePipeline 샘플(fake_visual.json)에 있는 세계관 규칙


async def _register(client: AsyncClient) -> dict[str, str]:
    sfx = uuid.uuid4().hex[:8]
    r = await client.post(
        "/auth/register",
        json={"email": f"ac_{sfx}@x.com", "password": "secret123", "name": "Other"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _save_chapter(client: AsyncClient, pid: str, h: dict, no: int, edit_item: str | None) -> dict:
    """업로드 → 추출 → (RULE_001 편집) → 검수 → 저장. 추출 결과를 반환."""
    await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"{no}화 본문"}, headers=h
    )
    await client.post(f"/projects/{pid}/chapters/{no}/extract", headers=h)
    res = await poll_result(client, pid, no, h, stop=("extracted", "failed"))
    assert res["status"] == "extracted"
    if edit_item is not None:
        cur = next(x for x in res["canon_delta"]["worldview"] if x["entity_key"] == KEY)
        r = await client.patch(
            f"/projects/{pid}/chapters/{no}/delta/worldview/{KEY}",
            json={**cur, "item": edit_item},
            headers=h,
        )
        assert r.status_code == 200, r.text
    await client.post(f"/projects/{pid}/chapters/{no}/review", json=MANUAL_SAVE, headers=h)
    assert (await poll_result(client, pid, no, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/{no}/save", headers=h)).status_code == 200
    return res


async def _canon(client: AsyncClient, pid: str, h: dict, view: str, at: int | None = None) -> dict:
    params = {"view": view} | ({"at_chapter": at} if at is not None else {})
    r = await client.get(f"/projects/{pid}/canon", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _wv(body: dict) -> dict[str, str]:
    keys = [it["entity_key"] for it in body["items"]]
    assert len(keys) == len(set(keys))  # 시점마다 항목당 1행
    return {it["entity_key"]: it["item"] for it in body["items"]}


async def test_at_chapter_version_chain(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    res1 = await _save_chapter(client, pid, h, 1, edit_item=None)
    original = next(x["item"] for x in res1["canon_delta"]["worldview"] if x["entity_key"] == KEY)
    await _save_chapter(client, pid, h, 2, edit_item="2화에서 바뀐 규칙")
    await _save_chapter(client, pid, h, 3, edit_item="3화에서 다시 바뀐 규칙")

    assert _wv(await _canon(client, pid, h, "worldview", 1))[KEY] == original
    assert _wv(await _canon(client, pid, h, "worldview", 2))[KEY] == "2화에서 바뀐 규칙"
    assert _wv(await _canon(client, pid, h, "worldview", 3))[KEY] == "3화에서 다시 바뀐 규칙"
    assert _wv(await _canon(client, pid, h, "worldview"))[KEY] == "3화에서 다시 바뀐 규칙"
    # 0화 시점 = 아무것도 없음
    assert (await _canon(client, pid, h, "worldview", 0))["items"] == []

    # 시점이 뒤로 가도 다른 항목(1화 출처, 변경 없음)은 그대로 보인다
    assert set(_wv(await _canon(client, pid, h, "worldview", 1))) == set(
        _wv(await _canon(client, pid, h, "worldview", 3))
    )


async def test_views_include_entity_key_and_attrs(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _save_chapter(client, pid, h, 1, edit_item=None)

    chars = await _canon(client, pid, h, "characters", 1)
    assert chars["nodes"]
    for n in chars["nodes"]:
        assert n["entity_key"] == n["id"] and "attrs" in n
    for e in chars["edges"]:
        assert e["entity_key"]

    spaces = await _canon(client, pid, h, "spaces")
    assert spaces["items"]
    for it in spaces["items"]:
        assert it["entity_key"] and "attrs" in it

    for view in ("worldview", "timeline", "events", "foreshadowing"):
        for it in (await _canon(client, pid, h, view))["items"]:
            assert it["entity_key"], view


async def test_at_chapter_forbidden_missing_and_invalid(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    other = await _register(client)
    r = await client.get(
        f"/projects/{project_id}/canon", params={"view": "worldview", "at_chapter": 1}, headers=other
    )
    assert r.status_code == 403
    r = await client.get(
        f"/projects/{uuid.uuid4()}/canon", params={"view": "worldview", "at_chapter": 1}, headers=auth_headers
    )
    assert r.status_code == 404
    r = await client.get(
        f"/projects/{project_id}/canon", params={"view": "worldview", "at_chapter": -1}, headers=auth_headers
    )
    assert r.status_code == 400


# ── 철회 / 복원 행 (서비스 레벨) ─────────────────────────────
def _w(key: str, item: str) -> dict:
    return {"entity_key": key, "item": item}


async def test_at_chapter_excludes_retired_and_includes_restored():
    async with SessionLocal() as s:
        user = await UserRepository(s).create(
            f"acr_{uuid.uuid4().hex[:8]}@x.com", hash_password("x"), "t"
        )
        project = Project(owner_id=user.id, name="at-chapter-retire")
        s.add(project)
        await s.flush()
        pid = project.id
        cs = CanonService(s)

        await cs.merge_delta(pid, {"worldview": [_w("a", "A1"), _w("b", "B1")]}, 1)
        # 2화: a 를 바꾸고(v2) c, d 추가
        await cs.merge_delta(pid, {"worldview": [_w("a", "A2"), _w("c", "C2"), _w("d", "D2")]}, 2)
        # 2화 재저장: a, d 가 빠짐 → a v2 철회 + a v1 복원, d 철회(직전 버전 없음)
        stats = await cs.merge_delta(pid, {"worldview": [_w("c", "C2")]}, 2)
        await s.commit()
        assert stats["retired"] == 2 and stats["restored"] == 1

        async def at(n: int | None) -> dict[str, str]:
            body = await cs.get_view(pid, "worldview", n)
            keys = [it["entity_key"] for it in body["items"]]
            assert len(keys) == len(set(keys))
            return {it["entity_key"]: it["item"] for it in body["items"]}

        assert await at(1) == {"a": "A1", "b": "B1"}
        # 철회된 a v2(superseded_at=source=2), d 는 빠지고 복원된 a v1(superseded_at=NULL)이 잡힌다
        assert await at(2) == {"a": "A1", "b": "B1", "c": "C2"}
        assert await at(5) == await at(None) == {"a": "A1", "b": "B1", "c": "C2"}
