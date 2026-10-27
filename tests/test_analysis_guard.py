"""분석 중복 실행 409 + 고착 복구(D8), 저장 본체 분리(save_chapter) 회귀."""
from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import ChapterStatus
from app.repository.chapter_repo import ChapterRepository
from app.service.chapter_service import ChapterService
from tests.util import poll_result


async def _upload(client: AsyncClient, pid: str, h: dict, no: int = 1) -> None:
    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"{no}화 본문"}, headers=h
    )
    assert r.status_code == 201, r.text


async def _age_chapter(pid: str, no: int, minutes: int) -> None:
    """updated_at 을 과거로 돌려 고착 상황을 만든다(워커가 죽은 척)."""
    async with SessionLocal() as s:
        await s.execute(
            text(
                "UPDATE chapters SET updated_at = now() - make_interval(mins => :m)"
                " WHERE project_id = :p AND chapter_no = :n"
            ),
            {"m": minutes, "p": uuid.UUID(pid), "n": no},
        )
        await s.commit()


async def _set_status(pid: str, no: int, status: str) -> None:
    async with SessionLocal() as s:
        ch = await ChapterRepository(s).get(uuid.UUID(pid), no)
        ch.status = status
        await s.commit()


# ── 중복 실행 409 ────────────────────────────────────────────
async def test_duplicate_requests_while_extracting_are_409(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h)
    assert (await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)).status_code == 202

    for action in ("extract", "review", "analyze"):
        r = await client.post(f"/projects/{pid}/chapters/1/{action}", headers=h)
        assert r.status_code == 409, action
        body = r.json()
        assert body["current_status"] == "extracting"
        assert "extracting" in body["detail"]

    assert (await poll_result(client, pid, 1, h, stop=("extracted", "failed")))["status"] == "extracted"


async def test_duplicate_requests_while_reviewing_are_409(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h)
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    await poll_result(client, pid, 1, h, stop=("extracted",))
    assert (await client.post(f"/projects/{pid}/chapters/1/review", headers=h)).status_code == 202

    r = await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert r.status_code == 409 and r.json()["current_status"] == "reviewing"
    await poll_result(client, pid, 1, h)


# ── 고착 복구 ────────────────────────────────────────────────
async def test_stale_extracting_is_failed_then_accepted(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h)
    await _set_status(pid, 1, ChapterStatus.extracting.value)  # 워커 없이 진행 중으로 고착

    # 아직 기준 시간 안 → 409
    r = await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert r.status_code == 409

    await _age_chapter(pid, 1, settings.analysis_stale_threshold_minutes + 1)
    r = await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert r.status_code == 202  # failed 로 기록된 뒤 새 요청을 받아줌
    assert (await poll_result(client, pid, 1, h, stop=("extracted", "failed")))["status"] == "extracted"


async def test_stale_marks_failed_with_stage(client: AsyncClient, auth_headers: dict, project_id: str):
    """고착 판정 시 failed + stage(현재 단계) + 사유가 남는다 (그 뒤 요청이 거절돼도)."""
    h, pid = auth_headers, project_id
    await _upload(client, pid, h)
    await _set_status(pid, 1, ChapterStatus.reviewing.value)
    await _age_chapter(pid, 1, settings.analysis_stale_threshold_minutes + 5)

    # reviewing 고착 → failed(review) 기록. 추출 결과(canon_delta)가 없는 고착이라 review 는 409.
    r = await client.post(f"/projects/{pid}/chapters/1/review", headers=h)
    assert r.status_code == 409 and "current_status" not in r.json()

    d = (await client.get(f"/projects/{pid}/chapters/1", headers=h)).json()
    assert d["status"] == "failed"
    assert d["failed_stage"] == "review"
    assert d["failed_detail"] == ChapterService.STALE_DETAIL

    # 재추출로 복구
    assert (await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)).status_code == 202
    await poll_result(client, pid, 1, h, stop=("extracted", "failed"))


async def test_stale_analyze_accepted(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h)
    await _set_status(pid, 1, ChapterStatus.extracting.value)
    await _age_chapter(pid, 1, settings.analysis_stale_threshold_minutes)  # 경계값(=기준)도 고착
    assert (await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)).status_code == 202
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"


# ── 저장 본체(save_chapter) ─────────────────────────────────
async def test_save_chapter_is_idempotent_and_shared(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    """API save 와 같은 본체를 서비스에서 직접 불러도 병합은 한 번만."""
    h, pid = auth_headers, project_id
    await _upload(client, pid, h)
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    await poll_result(client, pid, 1, h, stop=("extracted",))
    await client.post(f"/projects/{pid}/chapters/1/review", json={"auto_save": False}, headers=h)
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"

    async with SessionLocal() as s:
        ch = await ChapterRepository(s).get(uuid.UUID(pid), 1)
        r1 = await ChapterService(s).save_chapter(ch)
        r2 = await ChapterService(s).save_chapter(ch)
    assert r1.status == r2.status == "saved"

    r = await client.post(f"/projects/{pid}/chapters/1/save", headers=h)
    assert r.status_code == 200 and r.json() == {"chapter_no": 1, "status": "saved"}

    async with SessionLocal() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM canon_worldview WHERE project_id = :p"),
                {"p": uuid.UUID(pid)},
            )
        ).scalar_one()
        cur = (
            await s.execute(
                text(
                    "SELECT count(*) FROM canon_worldview WHERE project_id = :p AND version > 1"
                ),
                {"p": uuid.UUID(pid)},
            )
        ).scalar_one()
    assert n > 0 and cur == 0  # 세 번 저장해도 버전이 늘지 않는다
