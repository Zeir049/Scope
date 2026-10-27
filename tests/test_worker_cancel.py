"""고착 기준(max(ANALYSIS_STALE_MINUTES, JOB_TIMEOUT/60+5)) + 워커 취소(arq job_timeout) 시 failed 기록."""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Chapter
from app.pipeline.fake import FakePipeline
from app.repository.analysis_repo import AnalysisRepository
from app.repository.chapter_repo import ChapterRepository
from app.service.chapter_service import ChapterService
from app.workers import tasks
from tests.util import poll_result


# ── 고착 기준 ────────────────────────────────────────────────
def _chapter_updated(minutes_ago: float) -> Chapter:
    return Chapter(updated_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago))


def test_stale_threshold_never_shorter_than_job_timeout(monkeypatch):
    monkeypatch.setattr(settings, "analysis_stale_minutes", 10)
    monkeypatch.setattr(settings, "job_timeout_seconds", 900)
    assert settings.analysis_stale_threshold_minutes == 20  # 900//60 + 5
    assert ChapterService.is_stale(_chapter_updated(15)) is False  # 설정(10분)은 넘었지만 기준 미만
    assert ChapterService.is_stale(_chapter_updated(19.5)) is False
    assert ChapterService.is_stale(_chapter_updated(21)) is True


def test_stale_threshold_uses_setting_when_longer(monkeypatch):
    monkeypatch.setattr(settings, "analysis_stale_minutes", 60)
    monkeypatch.setattr(settings, "job_timeout_seconds", 900)
    assert settings.analysis_stale_threshold_minutes == 60
    assert ChapterService.is_stale(_chapter_updated(30)) is False
    assert ChapterService.is_stale(_chapter_updated(61)) is True


def test_default_threshold_is_20_minutes():
    from app.core.config import Settings

    fields = Settings.model_fields  # .env 값과 무관하게 코드 기본값을 본다
    assert fields["analysis_stale_minutes"].default == 20
    assert max(20, fields["job_timeout_seconds"].default // 60 + 5) == 20


# ── 취소 처리 ────────────────────────────────────────────────
class SlowPipeline(FakePipeline):
    """파이프라인 호출이 오래 걸리는 Fake — 그 사이에 작업을 취소한다."""

    async def extract_chapter(self, chapter_text, canon, title=None, *, chapter_no=None):
        await asyncio.sleep(30)
        raise AssertionError("취소됐어야 한다")

    async def review_chapter(self, chapter_text, canon, delta, title=None, *, chapter_no=None):
        await asyncio.sleep(30)
        raise AssertionError("취소됐어야 한다")


async def _state(pid: str, no: int = 1) -> tuple[str, dict | None]:
    async with SessionLocal() as s:
        ch = await ChapterRepository(s).get(uuid.UUID(pid), no)
        row = await AnalysisRepository(s).get_latest(ch.id)
        return ch.status, (row.raw_output if row else None)


async def _set_status(pid: str, status: str, no: int = 1) -> None:
    async with SessionLocal() as s:
        ch = await ChapterRepository(s).get(uuid.UUID(pid), no)
        ch.status = status
        await s.commit()


async def _run_and_cancel(coro) -> None:
    task = asyncio.create_task(coro)
    await asyncio.sleep(0.5)  # 파이프라인 호출(sleep) 안으로 들어갈 시간
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _extracted(client: AsyncClient, pid: str, h: dict) -> None:
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert (await poll_result(client, pid, 1, h, stop=("extracted", "failed")))["status"] == "extracted"


async def test_cancel_during_review_records_failure(
    client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch
):
    h, pid = auth_headers, project_id
    await _extracted(client, pid, h)
    await _set_status(pid, "reviewing")  # start_review 가 한 것처럼
    monkeypatch.setattr(tasks, "get_pipeline", lambda: SlowPipeline())

    await _run_and_cancel(tasks.run_review(uuid.UUID(pid), 1, auto_save=True))

    status, raw = await _state(pid)
    assert status == "failed"
    assert raw == {"error": tasks.CANCEL_DETAIL, "stage": "review"}
    # 추출 결과는 남아 있으니 재검수로 복구 가능
    monkeypatch.setattr(tasks, "get_pipeline", lambda: FakePipeline())
    assert (await client.post(f"/projects/{pid}/chapters/1/review", headers=h)).status_code == 202
    assert (await poll_result(client, pid, 1, h, stop=("saved", "failed")))["status"] == "saved"


async def test_cancel_during_extraction_records_failure(
    client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch
):
    h, pid = auth_headers, project_id
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    await _set_status(pid, "extracting")
    monkeypatch.setattr(tasks, "get_pipeline", lambda: SlowPipeline())

    await _run_and_cancel(tasks.run_extraction(uuid.UUID(pid), 1))

    status, raw = await _state(pid)
    assert status == "failed"
    assert raw == {"error": tasks.CANCEL_DETAIL, "stage": "extract"}


async def test_cancel_after_review_commit_is_not_recorded(
    client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch
):
    """reviewed 커밋 뒤(자동 저장 중) 취소는 failed 로 덮지 않는다 — 검수 결과는 남는다."""
    h, pid = auth_headers, project_id
    await _extracted(client, pid, h)
    await _set_status(pid, "reviewing")

    async def slow_save(self, chapter):  # noqa: ANN001
        await asyncio.sleep(30)

    monkeypatch.setattr(tasks, "get_pipeline", lambda: _InstantPipeline())
    monkeypatch.setattr(ChapterService, "save_chapter", slow_save)

    await _run_and_cancel(tasks.run_review(uuid.UUID(pid), 1, auto_save=True))

    status, raw = await _state(pid)
    assert status == "reviewed" and raw is None


class _InstantPipeline(FakePipeline):
    async def review_chapter(self, chapter_text, canon, delta, title=None, *, chapter_no=None):
        from app.pipeline.interface import ReviewOutput

        return ReviewOutput(contradictions=[])
