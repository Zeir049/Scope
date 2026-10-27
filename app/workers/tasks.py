"""비동기 분석 작업.

지금은 FastAPI BackgroundTasks로 같은 프로세스에서 실행(FakePipeline 즉시 처리용).
나중에 무거운 LLM 분석은 이 함수를 arq/Celery 태스크로 그대로 옮기면 된다
(자체 DB 세션을 열어 쓰므로 요청 수명과 분리되어 있음).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import ChapterStatus
from app.pipeline.factory import get_pipeline
from app.pipeline.interface import CanonDelta
from app.repository.analysis_repo import AnalysisRepository
from app.repository.chapter_repo import ChapterRepository
from app.repository.notification_repo import NotificationRepository
from app.repository.project_repo import ProjectRepository
from app.service.canon_service import CanonService
from app.service.chapter_service import ChapterService

logger = logging.getLogger(__name__)

CANCEL_DETAIL = "작업 시간 초과(arq job_timeout)"


async def _notify_owner(session, project_id: uuid.UUID, message: str) -> None:
    """분석 결과를 프로젝트 소유자에게 알림(기능 플래그 ON일 때만)."""
    if not settings.enable_notifications:
        return
    project = await ProjectRepository(session).get_by_id(project_id)
    if project is not None:
        await NotificationRepository(session).create(
            project.owner_id, "analysis", message
        )


async def _record_failure(
    project_id: uuid.UUID, chapter_no: int, stage: str, detail: str
) -> None:
    """어느 단계든 실패 시 별도 트랜잭션으로 failed + 실패단계/사유를 기록."""
    async with SessionLocal() as session:
        chapters = ChapterRepository(session)
        analysis = AnalysisRepository(session)
        chapter = await chapters.get(project_id, chapter_no)
        if chapter is None:
            return
        row = await analysis.get_latest(chapter.id)
        if row is None:
            row = await analysis.create_pending(chapter.id)
        await analysis.save_failure(row, detail, stage=stage)
        chapter.status = ChapterStatus.failed.value
        await ProjectRepository(session).touch(project_id)
        await _notify_owner(session, project_id, f"{chapter_no}화 {stage} 단계에서 실패했습니다.")
        await session.commit()


async def _fail_on_cancel(
    session, project_id: uuid.UUID, chapter_no: int, stage: str  # noqa: ANN001 - AsyncSession
) -> None:
    """작업이 취소(arq job_timeout 등)될 때: 진행 중 트랜잭션을 버리고 failed 를 기록한다.

    rollback 을 먼저 해야 이 세션이 잡고 있을지 모를 회차 행 잠금이 풀려 기록이 막히지 않는다.
    """
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001 - 정리 실패해도 기록은 시도
        logger.exception("rollback on cancel failed: project=%s ch=%s", project_id, chapter_no)
    await _record_failure(project_id, chapter_no, stage, CANCEL_DETAIL)


async def _record_cancel(session, project_id: uuid.UUID, chapter_no: int, stage: str) -> None:  # noqa: ANN001
    """취소 중에도 기록이 끝까지 가도록 shield. 기록 실패는 로그만 남기고 취소는 그대로 전파."""
    logger.warning("%s cancelled: project=%s ch=%s", stage, project_id, chapter_no)
    try:
        await asyncio.shield(_fail_on_cancel(session, project_id, chapter_no, stage))
    except Exception:  # noqa: BLE001
        logger.exception("failed to record cancel: project=%s ch=%s", project_id, chapter_no)


async def run_extraction(project_id: uuid.UUID, chapter_no: int) -> bool:
    """1차 추출: extracting → extracted(성공) | failed(실패). 성공 시 True.

    캐논은 건드리지 않는다(불변원칙 3: 병합은 save 에서만).
    취소(asyncio.CancelledError — arq job_timeout)되면 failed 를 기록하고 다시 던진다.
    """
    fail_detail: str | None = None
    committed = False
    async with SessionLocal() as session:
        chapters = ChapterRepository(session)
        analysis = AnalysisRepository(session)
        chapter = await chapters.get(project_id, chapter_no)
        if chapter is None:
            logger.warning("run_extraction: chapter gone project=%s no=%s", project_id, chapter_no)
            return False
        row = await analysis.get_latest(chapter.id) or await analysis.create_pending(chapter.id)
        try:
            canon = await CanonService(session).build_snapshot(project_id)
            output = await get_pipeline().extract_chapter(
                chapter.raw_text or "", canon, title=chapter.title, chapter_no=chapter_no
            )
            await analysis.save_extraction(
                row,
                highlighted_text=output.highlighted_text,
                canon_delta=output.canon_delta.model_dump(),
                visual_json=output.visual_json,
            )
            chapter.status = ChapterStatus.extracted.value
            await ProjectRepository(session).touch(project_id)
            await session.commit()
            committed = True
            logger.info("extraction done: project=%s ch=%s -> extracted", project_id, chapter_no)
            return True
        except asyncio.CancelledError:
            if not committed:
                await _record_cancel(session, project_id, chapter_no, "extract")
            raise
        except Exception as e:  # noqa: BLE001 - 실패도 상태로 남긴다
            await session.rollback()
            fail_detail = str(e)
            logger.exception("extraction failed: project=%s ch=%s", project_id, chapter_no)
    # 여기 도달 = 실패 경로 (실패 기록은 별도 트랜잭션)
    await _record_failure(project_id, chapter_no, "extract", fail_detail or "unknown error")
    return False


async def run_review(
    project_id: uuid.UUID, chapter_no: int, auto_save: bool = False
) -> bool:
    """2차 검수: reviewing → reviewed(성공) [→ saved(auto_save)] | failed(실패). 성공 시 True.

    1차에서 저장한 canon_delta + N-1화 시점 캐논(D6: 자기 자신과 뒤 회차 기여 제외)을
    파이프라인에 넘겨 모순만 받아 저장한다. 검수 자체는 캐논을 건드리지 않는다.
    auto_save 면 reviewed 를 커밋한 뒤 저장 본체(save_chapter)로 병합한다(D4).
    reviewed 커밋 전에 취소되면 failed 를 기록하고 다시 던진다(그 뒤의 취소는 기록 안 함).
    """
    fail_detail: str | None = None
    committed = False
    async with SessionLocal() as session:
        chapters = ChapterRepository(session)
        analysis = AnalysisRepository(session)
        chapter = await chapters.get(project_id, chapter_no)
        if chapter is None:
            logger.warning("run_review: chapter gone project=%s no=%s", project_id, chapter_no)
            return False
        row = await analysis.get_latest(chapter.id)
        try:
            canon = await CanonService(session).build_snapshot(
                project_id, at_chapter=chapter_no - 1
            )
            delta = CanonDelta.model_validate(row.canon_delta) if row and row.canon_delta else CanonDelta()
            output = await get_pipeline().review_chapter(
                chapter.raw_text or "", canon, delta, title=chapter.title, chapter_no=chapter_no
            )
            if row is not None:
                row.raw_output = None  # 검수 실패 후 재검수가 성공하면 이전 실패 기록을 비운다
            await analysis.add_contradictions(chapter.id, output.contradictions)
            chapter.status = ChapterStatus.reviewed.value
            await ProjectRepository(session).touch(project_id)
            await _notify_owner(session, project_id, f"{chapter_no}화 검수가 완료되었습니다.")
            await session.commit()
            committed = True
            logger.info("review done: project=%s ch=%s -> reviewed", project_id, chapter_no)
        except asyncio.CancelledError:
            if not committed:
                await _record_cancel(session, project_id, chapter_no, "review")
            raise
        except Exception as e:  # noqa: BLE001 - 실패도 상태로 남긴다
            await session.rollback()
            fail_detail = str(e)
            logger.exception("review failed: project=%s ch=%s", project_id, chapter_no)
        else:
            # reviewed 를 먼저 커밋해 두고(폴링이 reviewed 를 볼 수 있음) 이어서 저장한다.
            if auto_save:
                await _auto_save(session, chapter)
            return True
    await _record_failure(project_id, chapter_no, "review", fail_detail or "unknown error")
    return False


async def _auto_save(session, chapter) -> None:  # noqa: ANN001 - AsyncSession, Chapter
    """검수 성공 후 자동 저장(D4). 실패해도 검수 결과(reviewed)는 남겨 POST /save 로 재시도 가능."""
    try:
        await ChapterService(session).save_chapter(chapter)
        logger.info("auto-saved: project=%s ch=%s", chapter.project_id, chapter.chapter_no)
    except Exception:  # noqa: BLE001 - reviewed 로 남겨 수동 저장 경로를 연다
        await session.rollback()
        logger.exception(
            "auto-save failed (left reviewed): project=%s ch=%s",
            chapter.project_id, chapter.chapter_no,
        )


async def run_full_analysis(project_id: uuid.UUID, chapter_no: int) -> None:
    """편의(analyze): 추출 → (성공 시) 검수를 연속 실행.

    상태: extracting → extracted → reviewing → reviewed (성공) | 중간 failed.
    """
    if not await run_extraction(project_id, chapter_no):
        return
    # 검수 전 reviewing 으로 전환(상태 단일 원천 유지)
    async with SessionLocal() as session:
        chapter = await ChapterRepository(session).get(project_id, chapter_no)
        if chapter is None or chapter.status != ChapterStatus.extracted.value:
            return
        chapter.status = ChapterStatus.reviewing.value
        await ProjectRepository(session).touch(project_id)
        await session.commit()
    await run_review(project_id, chapter_no)
