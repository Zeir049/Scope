"""검수 → 자동 저장(D4), 재검수(D5), 검수 비교 기준 = N-1화 시점 캐논(D6)."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.pipeline.fake import FakePipeline
from app.repository.chapter_repo import ChapterRepository
from app.workers import tasks
from tests.util import MANUAL_SAVE, poll_result

CANON_TABLES = [
    "canon_worldview", "canon_characters", "canon_relations", "canon_timeline",
    "canon_spaces", "canon_events", "canon_foreshadowing",
]
SAVED = ("saved", "failed")


class RecordingPipeline(FakePipeline):
    """FakePipeline 그대로 + 검수 때 받은 CanonSnapshot 을 기록 (인터페이스로만 주입)."""

    def __init__(self) -> None:
        self.review_snapshots: dict[int, object] = {}
        self.extract_snapshots: dict[int, object] = {}

    async def extract_chapter(self, chapter_text, canon, title=None, *, chapter_no=None):
        self.extract_snapshots[chapter_no] = canon
        return await super().extract_chapter(chapter_text, canon, title=title, chapter_no=chapter_no)

    async def review_chapter(self, chapter_text, canon, delta, title=None, *, chapter_no=None):
        self.review_snapshots[chapter_no] = canon
        return await super().review_chapter(
            chapter_text, canon, delta, title=title, chapter_no=chapter_no
        )


@pytest.fixture
def recorder(monkeypatch) -> RecordingPipeline:
    rec = RecordingPipeline()
    monkeypatch.setattr(tasks, "get_pipeline", lambda: rec)
    return rec


async def _upload_extract(client: AsyncClient, pid: str, h: dict, no: int) -> dict:
    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"{no}화 본문"}, headers=h
    )
    assert r.status_code == 201, r.text
    await client.post(f"/projects/{pid}/chapters/{no}/extract", headers=h)
    res = await poll_result(client, pid, no, h, stop=("extracted", "failed"))
    assert res["status"] == "extracted"
    return res


async def _review(client: AsyncClient, pid: str, h: dict, no: int, **body) -> dict:
    r = await client.post(f"/projects/{pid}/chapters/{no}/review", json=body or None, headers=h)
    assert r.status_code == 202, r.text
    assert r.json() == {"chapter_no": no, "status": "reviewing"}
    return await poll_result(client, pid, no, h, stop=SAVED)


async def _canon_stats(pid: str) -> dict[str, tuple[int, int, int]]:
    """테이블별 (행 수, 최대 version, is_current 중복 항목 수)."""
    out = {}
    async with SessionLocal() as s:
        for t in CANON_TABLES:
            n, v = (
                await s.execute(
                    text(f"SELECT count(*), coalesce(max(version), 0) FROM {t} WHERE project_id = :p"),
                    {"p": uuid.UUID(pid)},
                )
            ).one()
            dup = (
                await s.execute(
                    text(
                        f"SELECT count(*) FROM (SELECT entity_key FROM {t} WHERE project_id = :p"
                        " AND is_current GROUP BY entity_key HAVING count(*) > 1) x"
                    ),
                    {"p": uuid.UUID(pid)},
                )
            ).scalar_one()
            out[t] = (n, v, dup)
    return out


# ── D4: 자동 저장 ────────────────────────────────────────────
async def test_review_auto_saves_by_default(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h, 1)
    res = await _review(client, pid, h, 1)  # 바디 없음 = auto_save true
    assert res["status"] == "saved"
    assert "contradictions" in res

    wv = (await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)).json()
    assert wv["items"]  # 캐논에 병합됨
    # 이미 saved 라 기존 save 호출은 멱등(review 폴링 → save 를 부르는 클라이언트 호환)
    r = await client.post(f"/projects/{pid}/chapters/1/save", headers=h)
    assert r.status_code == 200 and r.json() == {"chapter_no": 1, "status": "saved"}


async def test_review_auto_save_false_stops_at_reviewed(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h, 1)
    r = await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert r.status_code == 202
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"
    wv = (await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)).json()
    assert wv["items"] == []  # 아직 병합 안 됨
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200
    assert (await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)).json()["items"]


async def test_auto_save_and_manual_save_race_merges_once(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    """클라이언트가 reviewed 를 보자마자 save 를 불러도 병합은 한 번 (회차 행 잠금)."""
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h, 1)
    await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    res = await poll_result(client, pid, 1, h, stop=("reviewed", "saved", "failed"))
    if res["status"] == "reviewed":
        assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200
    assert (await poll_result(client, pid, 1, h, stop=SAVED))["status"] == "saved"
    stats = await _canon_stats(pid)
    assert all(v == 1 and dup == 0 for _, v, dup in stats.values() if v)


# ── D5: 재검수 ───────────────────────────────────────────────
async def test_re_review_saved_chapter(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    for no in (1, 2):
        await _upload_extract(client, pid, h, no)
        assert (await _review(client, pid, h, no))["status"] == "saved"
    before = await _canon_stats(pid)

    old = (await client.get(f"/projects/{pid}/chapters/2/result", headers=h)).json()["contradictions"]
    assert old
    cid = old[0]["id"]
    await client.patch(
        f"/projects/{pid}/chapters/2/contradictions/{cid}", json={"status": "confirmed"}, headers=h
    )

    # 2화 재검수 → reviewing → … → saved
    res = await _review(client, pid, h, 2)
    assert res["status"] == "saved"
    new = res["contradictions"]
    assert new and {c["id"] for c in new}.isdisjoint({c["id"] for c in old})  # 새 결과로 교체
    assert all(c["status"] == "pending" for c in new)  # 판정도 초기화

    # 1화 재검수 → N-1=0 시점 캐논이 비어 있어 FakePipeline 은 모순을 내지 않는다
    res1 = await _review(client, pid, h, 1)
    assert res1["status"] == "saved" and res1["contradictions"] == []

    # 델타가 같으니 병합은 unchanged — 행 수·version·is_current 1개 유지
    assert await _canon_stats(pid) == before
    assert all(dup == 0 for _, _, dup in before.values())


async def test_re_review_manual_save(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload_extract(client, pid, h, 1)
    await _review(client, pid, h, 1)
    before = await _canon_stats(pid)
    r = await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert r.status_code == 202
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200
    assert await _canon_stats(pid) == before


async def test_re_review_without_delta_is_409(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    async with SessionLocal() as s:  # 분석 결과 없이 saved 인 회차(예전 데이터 등)
        ch = await ChapterRepository(s).get(uuid.UUID(pid), 1)
        ch.status = "saved"
        await s.commit()
    r = await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    assert r.status_code == 409


async def test_review_from_other_states_is_409(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    r = await client.post(f"/projects/{pid}/chapters/1/review", headers=h)  # uploaded
    assert r.status_code == 409 and "saved" in r.json()["detail"]


# ── D6: 검수 비교 기준 = N-1화 시점 캐논 ─────────────────────
async def _save_with_edits(client, pid, h, no, *, add_key=None, change_rule=None):
    res = await _upload_extract(client, pid, h, no)
    if change_rule is not None:
        cur = next(x for x in res["canon_delta"]["worldview"] if x["entity_key"] == "RULE_001")
        r = await client.patch(
            f"/projects/{pid}/chapters/{no}/delta/worldview/RULE_001",
            json={**cur, "item": change_rule}, headers=h,
        )
        assert r.status_code == 200
    if add_key is not None:
        r = await client.post(
            f"/projects/{pid}/chapters/{no}/delta/worldview",
            json={"entity_key": add_key, "item": f"{add_key} 설정"}, headers=h,
        )
        assert r.status_code == 201
    assert (await _review(client, pid, h, no))["status"] == "saved"


async def test_review_snapshot_is_previous_chapter_canon(
    client: AsyncClient, auth_headers: dict, project_id: str, recorder: RecordingPipeline
):
    h, pid = auth_headers, project_id
    await _save_with_edits(client, pid, h, 1)
    snap1 = recorder.review_snapshots[1]
    assert snap1.up_to_chapter == 0 and snap1.worldview == [] and snap1.characters == []  # 0화 시점

    await _save_with_edits(client, pid, h, 2, add_key="only-ch2", change_rule="2화 규칙")
    await _save_with_edits(client, pid, h, 3, add_key="only-ch3")
    # 첫 검수(2화)도 N-1 기준: 1화 것만
    snap2_first = recorder.review_snapshots[2]
    assert {e["source_chapter"] for e in snap2_first.worldview} == {1}

    # 2화 재검수
    recorder.review_snapshots.clear()
    assert (await _review(client, pid, h, 2))["status"] == "saved"
    snap = recorder.review_snapshots[2]
    assert snap.up_to_chapter == 1
    keys = {e["entity_key"] for e in snap.worldview}
    assert "only-ch2" not in keys and "only-ch3" not in keys  # 자기 자신·뒤 회차 기여 제외
    rule = next(e for e in snap.worldview if e["entity_key"] == "RULE_001")
    assert rule["source_chapter"] == 1 and rule["item"] != "2화 규칙"  # 2화가 바꾼 버전이 아니라 1화 버전
    for field in ("worldview", "characters", "relations", "timeline", "spaces", "events", "foreshadowing"):
        assert all(e["source_chapter"] <= 1 for e in getattr(snap, field)), field

    # 추출 스냅샷은 그대로 현재 캐논(is_current) — 3화 추출 때 2화 기여가 들어 있었다
    ext3 = recorder.extract_snapshots[3]
    assert "only-ch2" in {e["entity_key"] for e in ext3.worldview}
    assert next(e for e in ext3.worldview if e["entity_key"] == "RULE_001")["item"] == "2화 규칙"
