"""캐논 유령 정리 테스트 — 재저장 시 델타에서 빠진 항목 철회 + 직전 버전 복원.

수정 원고 재분석(PUT 재업로드) 후 재저장하면, 이전 분석이 캐논에 넣었지만
새 분석에는 없는 항목이 current로 남는 문제(유령)를 막는다.
- 같은 회차 재저장에서 빠진 항목 → 철회(is_current=false, 행은 보존)
- 다른 회차 출처 항목은 불간섭
- 다른 회차가 만든 항목을 이 회차가 고쳤다가 철회하면 원래 버전 복원
- 철회 멱등 / 철회된 항목 재추가 시 버전 이어 매김
- API 레벨: [규칙] 파일 재업로드로 줄을 지우면 세계관에서도 사라짐
"""
from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import CanonWorldview, Project
from app.repository.user_repo import UserRepository
from app.service.canon_service import CanonService
from tests.util import poll_result


async def _setup(s):
    user = await UserRepository(s).create(
        f"cr_{uuid.uuid4().hex[:8]}@x.com", hash_password("x"), "t"
    )
    project = Project(owner_id=user.id, name="canon-retire-test")
    s.add(project)
    await s.flush()
    return project.id


def _wv(entity_key: str, item: str) -> dict:
    return {"entity_key": entity_key, "item": item}


async def _current_map(s, pid):
    rows = (
        await s.execute(
            select(CanonWorldview).where(
                CanonWorldview.project_id == pid,
                CanonWorldview.is_current.is_(True),
            )
        )
    ).scalars().all()
    return {r.entity_key: r for r in rows}


async def test_missing_item_is_retired_on_resave():
    """같은 회차 재저장에서 빠진 항목은 current에서 내려가되 행은 보존된다."""
    async with SessionLocal() as s:
        pid = await _setup(s)
        cs = CanonService(s)
        await cs.merge_delta(pid, {"worldview": [_wv("a", "A"), _wv("b", "B")]}, 1)
        stats = await cs.merge_delta(pid, {"worldview": [_wv("a", "A")]}, 1)  # b 빠짐
        await s.commit()

        cur = await _current_map(s, pid)
        assert set(cur) == {"a"}
        assert stats["retired"] == 1 and stats["restored"] == 0

        rows = (
            await s.execute(
                select(CanonWorldview).where(CanonWorldview.project_id == pid)
            )
        ).scalars().all()
        assert {r.entity_key for r in rows} == {"a", "b"}  # append-only: 행 보존
        b = next(r for r in rows if r.entity_key == "b")
        assert b.is_current is False and b.superseded_at_chapter == 1


async def test_other_chapters_items_untouched():
    """다른 회차 출처의 항목은 재저장이 절대 건드리지 않는다."""
    async with SessionLocal() as s:
        pid = await _setup(s)
        cs = CanonService(s)
        await cs.merge_delta(pid, {"worldview": [_wv("one", "1화 설정")]}, 1)
        await cs.merge_delta(pid, {"worldview": [_wv("two", "2화 설정")]}, 2)
        await cs.merge_delta(pid, {"worldview": []}, 2)  # 2화 재저장: 전부 빠짐
        await s.commit()

        assert set(await _current_map(s, pid)) == {"one"}


async def test_retire_restores_previous_chapter_version():
    """다른 회차가 만든 설정을 이 회차가 고쳤다가 철회하면 원래 버전이 복원된다."""
    async with SessionLocal() as s:
        pid = await _setup(s)
        cs = CanonService(s)
        await cs.merge_delta(pid, {"worldview": [_wv("k", "1화 원본")]}, 1)
        await cs.merge_delta(pid, {"worldview": [_wv("k", "3화 수정")]}, 3)  # v2(src3)
        stats = await cs.merge_delta(pid, {"worldview": []}, 3)  # 3화 재저장: k 빠짐
        await s.commit()

        cur = await _current_map(s, pid)
        assert cur["k"].item == "1화 원본" and cur["k"].version == 1
        assert stats["retired"] == 1 and stats["restored"] == 1


async def test_retire_idempotent_and_readd_continues_versioning():
    """철회는 멱등이고, 철회된 항목을 재추가하면 버전을 이어 매긴다."""
    async with SessionLocal() as s:
        pid = await _setup(s)
        cs = CanonService(s)
        await cs.merge_delta(pid, {"worldview": [_wv("a", "A")]}, 1)
        await cs.merge_delta(pid, {"worldview": []}, 1)          # 철회
        stats = await cs.merge_delta(pid, {"worldview": []}, 1)  # 한 번 더 → 변화 없음
        assert stats["retired"] == 0 and stats["restored"] == 0

        await cs.merge_delta(pid, {"worldview": [_wv("a", "A2")]}, 1)  # 재추가
        await s.commit()

        cur = await _current_map(s, pid)
        assert cur["a"].item == "A2" and cur["a"].version == 2  # v1 이력에 이어 매김


async def test_rules_file_reupload_removes_deleted_rule(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    """API 레벨: [규칙] 파일에서 줄을 지우고 재업로드하면 세계관에서도 사라진다."""
    h, pid = auth_headers, project_id

    async def analyze_and_save(no: int):
        assert (await client.post(f"/projects/{pid}/chapters/{no}/analyze", headers=h)).status_code == 202
        assert (await poll_result(client, pid, no, h))["status"] == "reviewed"
        assert (await client.post(f"/projects/{pid}/chapters/{no}/save", headers=h)).status_code == 200

    r = await client.post(
        f"/projects/{pid}/chapters",
        json={"chapter_no": 1, "title": "[규칙] 세계관.txt", "text": "- 규칙 하나\n- 규칙 둘"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    await analyze_and_save(1)

    r = await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)
    items = {it["item"] for it in r.json()["items"]}
    assert items == {"규칙 하나", "규칙 둘"}

    # 규칙 둘을 지운 파일로 재업로드 → 재분석 → 재저장
    r = await client.put(
        f"/projects/{pid}/chapters/1",
        json={"title": "[규칙] 세계관.txt", "text": "- 규칙 하나"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    await analyze_and_save(1)

    r = await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)
    items = {it["item"] for it in r.json()["items"]}
    assert items == {"규칙 하나"}  # 유령 없음
