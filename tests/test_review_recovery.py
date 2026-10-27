"""검수 실패·고착에서 재검수로 복구 + 캐논 기여가 있는 회차 삭제 금지."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.pipeline.fake import FakePipeline
from app.workers import tasks
from tests.util import poll_result

CANON_TABLES = [
    "canon_worldview", "canon_characters", "canon_relations", "canon_timeline",
    "canon_spaces", "canon_events", "canon_foreshadowing",
]
DONE = ("saved", "failed")


class FlakyPipeline(FakePipeline):
    """fail_review / fail_extract 가 켜져 있으면 해당 단계에서 예외 (인터페이스로 주입)."""

    def __init__(self) -> None:
        self.fail_review = False
        self.fail_extract = False

    async def extract_chapter(self, chapter_text, canon, title=None, *, chapter_no=None):
        if self.fail_extract:
            raise RuntimeError("추출 실패(테스트)")
        return await super().extract_chapter(chapter_text, canon, title=title, chapter_no=chapter_no)

    async def review_chapter(self, chapter_text, canon, delta, title=None, *, chapter_no=None):
        if self.fail_review:
            raise RuntimeError("검수 실패(테스트)")
        return await super().review_chapter(chapter_text, canon, delta, title=title, chapter_no=chapter_no)


@pytest.fixture
def flaky(monkeypatch) -> FlakyPipeline:
    pipe = FlakyPipeline()
    monkeypatch.setattr(tasks, "get_pipeline", lambda: pipe)
    return pipe


async def _upload_extract(client: AsyncClient, pid: str, h: dict, no: int = 1) -> None:
    await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"{no}화 본문"}, headers=h
    )
    await client.post(f"/projects/{pid}/chapters/{no}/extract", headers=h)
    assert (await poll_result(client, pid, no, h, stop=("extracted", "failed")))["status"] == "extracted"


async def _review(client: AsyncClient, pid: str, h: dict, no: int = 1) -> dict:
    r = await client.post(f"/projects/{pid}/chapters/{no}/review", headers=h)
    assert r.status_code == 202, r.text
    return await poll_result(client, pid, no, h, stop=DONE)


async def _detail(client: AsyncClient, pid: str, h: dict, no: int = 1) -> dict:
    return (await client.get(f"/projects/{pid}/chapters/{no}", headers=h)).json()


async def _make_stale_reviewing(pid: str, no: int) -> None:
    async with SessionLocal() as s:
        await s.execute(
            text(
                "UPDATE chapters SET status = 'reviewing',"
                " updated_at = now() - make_interval(mins => :m)"
                " WHERE project_id = :p AND chapter_no = :n"
            ),
            {"m": 24 * 60, "p": uuid.UUID(pid), "n": no},
        )
        await s.commit()


async def _canon_count(pid: str) -> int:
    async with SessionLocal() as s:
        total = 0
        for t in CANON_TABLES:
            total += (
                await s.execute(text(f"SELECT count(*) FROM {t} WHERE project_id = :p"), {"p": uuid.UUID(pid)})
            ).scalar_one()
        return total


# ── 검수 실패 → 재검수 ───────────────────────────────────────
async def test_review_failure_then_review_again(
    client: AsyncClient, auth_headers: dict, project_id: str, flaky: FlakyPipeline
):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h)
    flaky.fail_review = True
    res = await _review(client, pid, h)
    assert res["status"] == "failed" and res["failed_stage"] == "review"

    flaky.fail_review = False
    r = await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    assert r.status_code == 202
    # 진행 중에는 마지막 실패 기록이 상세에 남아 있다
    d = await _detail(client, pid, h)
    assert d["status"] == "reviewing" and d["failed_stage"] == "review"

    assert (await poll_result(client, pid, 1, h, stop=DONE))["status"] == "saved"
    d = await _detail(client, pid, h)
    assert d["failed_stage"] is None and d["failed_detail"] is None  # 성공 후 실패 기록 비움


async def test_extract_failure_cannot_review(
    client: AsyncClient, auth_headers: dict, project_id: str, flaky: FlakyPipeline
):
    h, pid = auth_headers, project_id
    flaky.fail_extract = True
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert (await poll_result(client, pid, 1, h, stop=("extracted", "failed")))["status"] == "failed"

    r = await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    assert r.status_code == 409 and "추출 결과" in r.json()["detail"]


# ── 고착 → 재검수 ───────────────────────────────────────────
async def test_stale_reviewing_is_recovered_by_review(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h)
    await _make_stale_reviewing(pid, 1)

    r = await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    assert r.status_code == 202  # 고착 → failed 기록 → failed+delta 라 바로 재검수 시작
    d = await _detail(client, pid, h)
    assert d["status"] == "reviewing"
    assert d["failed_stage"] == "review" and "시간 초과" in d["failed_detail"]

    assert (await poll_result(client, pid, 1, h, stop=DONE))["status"] == "saved"


async def test_saved_then_stale_re_review_recovers_and_keeps_canon(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h)
    assert (await _review(client, pid, h))["status"] == "saved"
    before = await _canon_count(pid)

    await _make_stale_reviewing(pid, 1)  # saved → reviewing 중 워커 사망
    assert (await client.post(f"/projects/{pid}/chapters/1/review", headers=h)).status_code == 202
    assert (await poll_result(client, pid, 1, h, stop=DONE))["status"] == "saved"
    assert await _canon_count(pid) == before


# ── 삭제 가드 (캐논 기여) ────────────────────────────────────
async def test_delete_blocked_when_canon_contribution(
    client: AsyncClient, auth_headers: dict, project_id: str, flaky: FlakyPipeline
):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h)
    assert (await _review(client, pid, h))["status"] == "saved"

    r = await client.delete(f"/projects/{pid}/chapters/1", headers=h)
    assert r.status_code == 409 and "저장된 회차" in r.json()["detail"]  # 기존 상태 가드

    # saved 였다가 재검수 실패로 failed → 상태 가드는 통과하지만 캐논 기여 때문에 409
    flaky.fail_review = True
    assert (await _review(client, pid, h))["status"] == "failed"
    r = await client.delete(f"/projects/{pid}/chapters/1", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "캐논에 반영된 회차는 삭제할 수 없습니다."


async def test_delete_failed_without_contribution(
    client: AsyncClient, auth_headers: dict, project_id: str, flaky: FlakyPipeline
):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h)
    flaky.fail_review = True
    assert (await _review(client, pid, h))["status"] == "failed"
    assert (await client.delete(f"/projects/{pid}/chapters/1", headers=h)).status_code == 204


async def test_has_contribution_counts_retired_rows():
    """철회된 행(is_current=false)도 기여로 본다."""
    from app.core.security import hash_password
    from app.models import Project
    from app.repository.user_repo import UserRepository
    from app.service.canon_service import CanonService

    async with SessionLocal() as s:
        user = await UserRepository(s).create(f"hc_{uuid.uuid4().hex[:8]}@x.com", hash_password("x"), "t")
        project = Project(owner_id=user.id, name="has-contribution")
        s.add(project)
        await s.flush()
        cs = CanonService(s)
        assert await cs.has_contribution(project.id, 2) is False
        await cs.merge_delta(project.id, {"spaces": [{"entity_key": "s", "place": "집"}]}, 2)
        await cs.merge_delta(project.id, {}, 2)  # 2화 재저장에서 빠짐 → 철회
        await s.commit()
        assert await cs.has_contribution(project.id, 2) is True
        assert await cs.has_contribution(project.id, 1) is False


# ── 저장 후 수정 공식 경로 (D10) ─────────────────────────────
async def test_edit_after_save_official_path(client: AsyncClient, auth_headers: dict, project_id: str):
    """review(auto_save:false) → reviewed → 델타 편집(→ extracted) → review → saved, 캐논은 버전업."""
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h)
    assert (await _review(client, pid, h))["status"] == "saved"

    r = await client.post(f"/projects/{pid}/chapters/1/review", json={"auto_save": False}, headers=h)
    assert r.status_code == 202
    res = await poll_result(client, pid, 1, h)
    assert res["status"] == "reviewed"

    cur = next(x for x in res["canon_delta"]["worldview"] if x["entity_key"] == "RULE_001")
    r = await client.patch(
        f"/projects/{pid}/chapters/1/delta/worldview/RULE_001", json={**cur, "item": "저장 후 고친 규칙"}, headers=h
    )
    assert r.status_code == 200
    d = await _detail(client, pid, h)
    assert d["status"] == "extracted"
    # 편집 직후 save 는 409 (모순이 낡아 다시 검수해야 함)
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 409
    # 편집 중에도 캐논 기여가 있으니 삭제 불가
    assert (await client.delete(f"/projects/{pid}/chapters/1", headers=h)).status_code == 409

    assert (await _review(client, pid, h))["status"] == "saved"
    wv = (await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)).json()["items"]
    assert next(i for i in wv if i["entity_key"] == "RULE_001")["item"] == "저장 후 고친 규칙"
    async with SessionLocal() as s:
        v = (
            await s.execute(
                text("SELECT max(version) FROM canon_worldview WHERE project_id = :p AND entity_key = 'RULE_001'"),
                {"p": uuid.UUID(pid)},
            )
        ).scalar_one()
    assert v == 2  # 덮어쓰기가 아니라 새 버전
