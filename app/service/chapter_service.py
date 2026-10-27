"""회차 비즈니스 로직. 업로드/목록/상세/삭제 + 분석 시작·결과·저장."""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, DomainError, NotFoundError
from app.models import (
    AnalysisResult,
    Chapter,
    ChapterKind,
    ChapterStatus,
    ContradictionStatus,
    User,
)
from app.pipeline.interface import CATEGORY_MODELS
from app.repository.analysis_repo import AnalysisRepository
from app.repository.chapter_repo import ChapterRepository
from app.repository.project_repo import ProjectRepository
from app.schemas.analysis import (
    AnalyzeAccepted,
    ContradictionItem,
    ContradictionStatusUpdate,
    ResultOut,
    SaveResult,
    VisualOut,
)
from app.schemas.chapter import ChapterDetailOut, ChapterListOut, ChapterOut
from app.service.canon_service import CanonService
from app.service.ownership import assert_owned

logger = logging.getLogger(__name__)

_KINDS = {k.value for k in ChapterKind}
_CONTRADICTION_STATUSES = {s.value for s in ContradictionStatus}


def content_hash(text: str | None) -> str | None:
    """파싱된 원문의 sha256 hex (D3 중복 판단). 0004 마이그레이션의 SQL 계산과 같은 값."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChapterService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.chapters = ChapterRepository(session)
        self.projects = ProjectRepository(session)
        self.analysis = AnalysisRepository(session)

    async def _owned_chapter(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> Chapter:
        assert_owned(await self.projects.get_by_id(project_id), user)
        chapter = await self.chapters.get(project_id, chapter_no)
        if chapter is None:
            raise NotFoundError(f"{chapter_no}화를 찾을 수 없습니다.")
        return chapter

    async def _touch_project(self, project_id: uuid.UUID) -> None:
        """회차 생성/교체/상태 전환/삭제 시 프로젝트 updated_at 갱신(목록 정렬용)."""
        await self.projects.touch(project_id)

    @staticmethod
    def _validate_kind(kind: str) -> str:
        if kind not in _KINDS:
            raise DomainError(
                f"알 수 없는 회차 종류입니다: {kind}. 가능: {', '.join(sorted(_KINDS))}"
            )
        return kind

    @staticmethod
    def _sync_hash(chapter: Chapter) -> None:
        """content_hash 를 현재 raw_text 기준으로 맞춘다."""
        chapter.content_hash = content_hash(chapter.raw_text)

    async def list_chapters(
        self, user: User, project_id: uuid.UUID
    ) -> ChapterListOut:
        assert_owned(await self.projects.get_by_id(project_id), user)
        rows = await self.chapters.list_by_project(project_id)
        return ChapterListOut(items=[ChapterOut.model_validate(c) for c in rows])

    @staticmethod
    def _check_text_size(text: str | None) -> None:
        """회차 텍스트 상한 (공개 환경에서 초대형 입력으로 파이프라인/DB 부하 방지)."""
        if text and len(text) > settings.max_chapter_chars:
            raise DomainError(
                f"회차 텍스트가 너무 깁니다 ({len(text):,}자). "
                f"최대 {settings.max_chapter_chars:,}자까지 올릴 수 있습니다."
            )

    async def upload(
        self,
        user: User,
        project_id: uuid.UUID,
        chapter_no: int,
        title: str | None,
        text: str | None,
        raw_path: str | None = None,
        kind: str = ChapterKind.narrative.value,
    ) -> ChapterOut:
        self._check_text_size(text)
        self._validate_kind(kind)
        assert_owned(await self.projects.get_by_id(project_id), user)
        if await self.chapters.get(project_id, chapter_no):
            raise ConflictError(f"{chapter_no}화는 이미 존재합니다.")
        digest = content_hash(text)
        if digest:
            dup = await self.chapters.find_by_hash(project_id, digest)
            if dup is not None:
                # D3: 같은 원문은 서버가 거절. 클라이언트는 existing_chapter_no 로 안내한다.
                raise ConflictError(
                    f"같은 내용의 원고가 이미 {dup.chapter_no}화로 올라가 있습니다.",
                    extra={"existing_chapter_no": dup.chapter_no},
                )
        chapter = await self.chapters.create(
            project_id=project_id,
            chapter_no=chapter_no,
            title=title,
            raw_text=text,
            raw_path=raw_path,
            kind=kind,
            content_hash=digest,
        )
        await self._touch_project(project_id)
        await self.s.commit()
        await self.s.refresh(chapter)
        logger.info("chapter uploaded: project=%s no=%s kind=%s", project_id, chapter_no, kind)
        return ChapterOut.model_validate(chapter)

    async def get_detail(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> ChapterDetailOut:
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        row = await self.analysis.get_latest(chapter.id)
        failed_stage = failed_detail = None
        if row is not None and row.raw_output:
            failed_stage = row.raw_output.get("stage")
            failed_detail = row.raw_output.get("error")
        return ChapterDetailOut(
            chapter_no=chapter.chapter_no,
            title=chapter.title,
            kind=chapter.kind,
            status=chapter.status,
            raw_text=chapter.raw_text,
            raw_path=chapter.raw_path,
            content_hash=chapter.content_hash,
            created_at=chapter.created_at,
            updated_at=chapter.updated_at,
            failed_stage=failed_stage,
            failed_detail=failed_detail,
            contradiction_count=await self.analysis.count_contradictions(chapter.id),
        )

    # 삭제 불가: 저장됨(캐논 기여가 있음) / 파이프라인 진행 중(워커가 행을 쓰는 중)
    _UNDELETABLE = {
        ChapterStatus.saved.value: "저장된 회차는 삭제할 수 없습니다.",
        ChapterStatus.extracting.value: "분석이 진행 중인 회차는 삭제할 수 없습니다.",
        ChapterStatus.reviewing.value: "분석이 진행 중인 회차는 삭제할 수 없습니다.",
    }

    async def delete(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> None:
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        reason = self._UNDELETABLE.get(chapter.status)
        if reason:
            raise ConflictError(reason)
        # 상태와 무관하게 캐논에 이 회차 출처 행(철회 포함)이 있으면 금지 — 출처 없는 캐논 방지.
        # saved 였다가 재검수 실패로 failed 가 된 회차 등. 판단은 DB에서 파생(원칙 4).
        if await CanonService(self.s).has_contribution(project_id, chapter_no):
            raise ConflictError("캐논에 반영된 회차는 삭제할 수 없습니다.")
        await self.chapters.delete(chapter)
        await self._touch_project(project_id)
        await self.s.commit()
        logger.info("chapter deleted: project=%s no=%s", project_id, chapter_no)

    async def update_content(
        self,
        user: User,
        project_id: uuid.UUID,
        chapter_no: int,
        title: str | None,
        text: str | None,
        raw_path: str | None = None,
        kind: str | None = None,
    ) -> ChapterOut:
        """회차 원고 교체(재업로드). 수정 원고 재분석 흐름의 진입점.

        kind 를 안 보내면 기존 종류 유지. 같은 원문이 다른 회차에 있어도 거절하지
        않는다(D3: 중복 거절은 새 업로드에서만) — 해시만 갱신.

        상태를 uploaded로 되돌리고 이전 분석 결과를 정리한다. 이미 저장(saved)된
        회차도 허용 — 재분석→재저장하면 캐논은 append-only 버전업으로 반영된다
        (불변원칙 2: 옛 버전은 is_current=false로 보존).
        """
        if not text or not text.strip():
            raise DomainError("파일(file) 또는 텍스트(text)가 필요합니다.")
        self._check_text_size(text)
        if kind is not None:
            self._validate_kind(kind)
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        if title is not None:
            chapter.title = title
        if kind is not None:
            chapter.kind = kind
        chapter.raw_text = text
        self._sync_hash(chapter)
        if raw_path is not None:
            chapter.raw_path = raw_path
        chapter.status = ChapterStatus.uploaded.value
        await self.analysis.clear_for_chapter(chapter.id)  # 낡은 결과/모순 정리
        await self._touch_project(project_id)
        await self.s.commit()
        await self.s.refresh(chapter)  # updated_at(onupdate) 재로딩
        logger.info("chapter re-uploaded: project=%s no=%s", project_id, chapter_no)
        return ChapterOut.model_validate(chapter)

    # ── 1차 추출 시작 (→ 백그라운드가 실제 추출) ────────────────
    async def _begin_pipeline(
        self, chapter: Chapter, status_value: str
    ) -> AnalyzeAccepted:
        """재분석 대비 이전 결과 정리 → 대기 행 생성 → 상태 전환."""
        await self.analysis.clear_for_chapter(chapter.id)
        await self.analysis.create_pending(chapter.id)
        self._sync_hash(chapter)
        chapter.status = status_value
        await self._touch_project(chapter.project_id)
        await self.s.commit()
        return AnalyzeAccepted(chapter_no=chapter.chapter_no, status=status_value)

    # 분석 파이프라인이 도는 중인 상태 (D8: 중복 실행 가드 대상)
    _RUNNING = {
        ChapterStatus.extracting.value: "extract",
        ChapterStatus.reviewing.value: "review",
    }
    STALE_DETAIL = "시간 초과로 중단된 작업"

    @staticmethod
    def is_stale(chapter: Chapter, now: dt.datetime | None = None) -> bool:
        """진행 중 상태로 고착 기준 이상 안 바뀌었는가 (워커 사망 추정).

        기준 = max(ANALYSIS_STALE_MINUTES, JOB_TIMEOUT_SECONDS//60 + 5) — 설정이 작업 상한보다
        짧게 잡혀도 아직 돌고 있을 수 있는 작업을 고착으로 보지 않는다.
        """
        if chapter.updated_at is None:
            return False
        now = now or dt.datetime.now(dt.timezone.utc)
        return now - chapter.updated_at >= dt.timedelta(
            minutes=settings.analysis_stale_threshold_minutes
        )

    async def _guard_not_running(self, chapter: Chapter) -> None:
        """extract/review/analyze 공통 가드 (D8).

        진행 중이면 409(+current_status). 단 고착(stale)이면 failed(stage=현재 단계)로
        기록·커밋하고 통과시킨다 — 이어지는 새 요청이 상태를 다시 판단한다.
        """
        stage = self._RUNNING.get(chapter.status)
        if stage is None:
            return
        if not self.is_stale(chapter):
            raise ConflictError(
                f"이미 분석이 진행 중입니다 (현재 상태: {chapter.status}).",
                extra={"current_status": chapter.status},
            )
        row = await self.analysis.get_latest(chapter.id) or await self.analysis.create_pending(
            chapter.id
        )
        await self.analysis.save_failure(row, self.STALE_DETAIL, stage=stage)
        chapter.status = ChapterStatus.failed.value
        await self._touch_project(chapter.project_id)
        await self.s.commit()
        await self.s.refresh(chapter)  # updated_at(onupdate) 재로딩
        logger.warning(
            "stale %s job marked failed: project=%s ch=%s",
            stage, chapter.project_id, chapter.chapter_no,
        )

    async def start_extraction(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> AnalyzeAccepted:
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        await self._guard_not_running(chapter)
        if chapter.status == ChapterStatus.saved.value:
            raise ConflictError("이미 저장된 회차는 다시 추출할 수 없습니다.")
        logger.info("extraction started: project=%s ch=%s", project_id, chapter_no)
        return await self._begin_pipeline(chapter, ChapterStatus.extracting.value)

    _REVIEWABLE = (
        ChapterStatus.extracted.value,
        ChapterStatus.saved.value,
        ChapterStatus.failed.value,  # canon_delta 가 있을 때만(아래에서 확인)
    )

    async def start_review(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> AnalyzeAccepted:
        """검수 시작. extracted(첫 검수) / saved(재검수, D5) / failed(추출 결과가 남아 있을 때).

        재검수는 재추출 없이 보관된 canon_delta 로 검수만 다시 한다. 그래서 결과 행은
        지우지 않고(clear_for_chapter 금지) 기존 모순만 지운다 — 작가의 ✓/✕ 판정도 함께 사라진다.
        failed 는 검수 단계 실패·고착처럼 canon_delta 가 보존된 경우만 받는다(추출 실패는 409).
        이때 raw_output 의 실패 기록은 두고(상세 API 가 마지막 실패 사유를 보여줌), 검수가
        성공하면 워커가 비운다.
        """
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        await self._guard_not_running(chapter)
        if chapter.status not in self._REVIEWABLE:
            raise ConflictError(
                "추출(extracted)·저장(saved)된 회차 또는 검수에 실패(failed)한 회차만 검수할 수 있습니다."
            )
        row = await self.analysis.get_latest(chapter.id)
        if row is None or row.canon_delta is None:
            raise ConflictError("검수할 추출 결과가 없습니다.")
        if chapter.status != ChapterStatus.extracted.value:
            await self.analysis.delete_contradictions(chapter.id)
            logger.info(
                "re-review from %s: project=%s ch=%s (contradictions cleared)",
                chapter.status, project_id, chapter_no,
            )
        self._sync_hash(chapter)
        chapter.status = ChapterStatus.reviewing.value
        await self._touch_project(project_id)
        await self.s.commit()
        logger.info("review started: project=%s ch=%s", project_id, chapter_no)
        return AnalyzeAccepted(
            chapter_no=chapter_no, status=ChapterStatus.reviewing.value
        )

    async def start_analysis(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> AnalyzeAccepted:
        """편의 API(analyze): 추출→검수 연속 실행의 시작(상태는 extracting)."""
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        await self._guard_not_running(chapter)
        if chapter.status == ChapterStatus.saved.value:
            raise ConflictError("이미 저장된 회차는 재분석할 수 없습니다.")
        logger.info("full analysis started: project=%s ch=%s", project_id, chapter_no)
        return await self._begin_pipeline(chapter, ChapterStatus.extracting.value)

    # ── 결과/진행상황 조회 (폴링) ──────────────────────────────
    # 진행중(폴링만) 상태
    _IN_PROGRESS = (
        ChapterStatus.uploaded.value,
        ChapterStatus.extracting.value,
        ChapterStatus.reviewing.value,
    )

    async def get_result(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> ResultOut:
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        status = chapter.status
        row = await self.analysis.get_latest(chapter.id)

        if status in self._IN_PROGRESS:
            return ResultOut(status=status, progress=row.progress if row else 0)

        if status == ChapterStatus.failed.value:
            detail = "분석에 실패했습니다."
            failed_stage = None
            if row and row.raw_output:
                detail = row.raw_output.get("error", detail)
                failed_stage = row.raw_output.get("stage")
            return ResultOut(status=status, detail=detail, failed_stage=failed_stage)

        highlighted = ""
        canon_delta = None
        if row:
            if row.highlighted:
                highlighted = row.highlighted.get("highlighted_text", "")
            canon_delta = row.canon_delta

        # extracted: 추출 결과(canon_delta)만. 사용자 검토 단계.
        if status == ChapterStatus.extracted.value:
            return ResultOut(
                status=status,
                highlighted_text=highlighted,
                canon_delta=canon_delta,
            )

        # reviewed | saved: 추출 결과 + 검수 결과(contradictions).
        rows = await self.analysis.list_contradictions(chapter.id)
        return ResultOut(
            status=status,
            highlighted_text=highlighted,
            canon_delta=canon_delta,
            contradictions=[ContradictionItem.model_validate(c) for c in rows],
        )

    async def update_contradiction_status(
        self,
        user: User,
        project_id: uuid.UUID,
        chapter_no: int,
        contradiction_id: uuid.UUID,
        body: ContradictionStatusUpdate,
    ) -> ContradictionItem:
        """작가의 모순 판정(confirmed / dismissed / 되돌리기 pending).

        chapters.status 는 건드리지 않는다 — 판정은 진행 상태가 아니다(불변원칙 4).
        """
        if body.status not in _CONTRADICTION_STATUSES:
            raise DomainError(
                f"알 수 없는 판정 상태입니다: {body.status}. "
                f"가능: {', '.join(sorted(_CONTRADICTION_STATUSES))}"
            )
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        item = await self.analysis.get_contradiction(chapter.id, contradiction_id)
        if item is None:
            raise NotFoundError("모순 항목을 찾을 수 없습니다.")
        item.status = body.status
        await self.s.commit()
        logger.info(
            "contradiction %s -> %s: project=%s ch=%s",
            contradiction_id, body.status, project_id, chapter_no,
        )
        return ContradictionItem.model_validate(item)

    async def get_visual(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> VisualOut:
        """회차별 시각화 원본 JSON 조회 (없으면 null — 프론트는 "시각화 데이터 없음"을 보여준다)."""
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        row = await self.analysis.get_latest(chapter.id)
        return VisualOut(
            chapter_no=chapter_no, visual=row.visual_json if row else None
        )

    # ── 추출 결과 항목 편집 (save 전, canon_delta JSON만 갱신) ──────
    # extracted/reviewed 에서만 편집 가능. canon_* 는 절대 안 건드린다(불변원칙 3).
    _EDITABLE = (ChapterStatus.extracted.value, ChapterStatus.reviewed.value)

    async def _editable_delta(
        self, user: User, project_id: uuid.UUID, chapter_no: int, category: str
    ) -> tuple[Chapter, AnalysisResult, dict, list, type]:
        """편집 공통 가드 → (chapter, row, delta_dict, category items, Delta 모델) 반환."""
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        if chapter.status not in self._EDITABLE:
            raise ConflictError(
                "추출(extracted) 또는 검토(reviewed) 상태에서만 편집할 수 있습니다."
            )
        model_cls = CATEGORY_MODELS.get(category)
        if model_cls is None:
            raise DomainError(f"알 수 없는 카테고리입니다: {category}")
        row = await self.analysis.get_latest(chapter.id)
        if row is None or row.canon_delta is None:
            raise ConflictError("편집할 추출 결과가 없습니다.")
        delta = dict(row.canon_delta)
        items = list(delta.get(category, []))
        return chapter, row, delta, items, model_cls

    @staticmethod
    def _validate_delta(model_cls: type, body: dict):
        try:
            return model_cls.model_validate(body)
        except ValidationError as e:
            raise DomainError(f"입력값 오류: {e.errors()[0]['msg']}") from e

    async def _persist_delta(
        self, chapter: Chapter, row: AnalysisResult, delta: dict, category: str, items: list
    ) -> None:
        delta[category] = items
        await self.analysis.update_canon_delta(row, delta)
        # reviewed 상태에서 델타를 편집하면 기존 모순은 편집 전 기준의 낡은 결과다.
        # → 모순을 지우고 status를 extracted로 되돌린다(사용자가 ② 검수를 다시 눌러
        #   최신 델타 기준으로 모순을 받은 뒤 저장). status는 단일 진실 원천(불변원칙 4).
        #   canon_* 는 여기서 절대 건드리지 않는다(불변원칙 3: 병합은 save 에서만).
        if chapter.status == ChapterStatus.reviewed.value:
            await self.analysis.delete_contradictions(chapter.id)
            chapter.status = ChapterStatus.extracted.value
            await self._touch_project(chapter.project_id)
            logger.info("reviewed→extracted on edit: project=%s ch=%s", chapter.project_id, chapter.chapter_no)
        await self.s.commit()

    async def update_delta_item(
        self, user: User, project_id: uuid.UUID, chapter_no: int,
        category: str, entity_key: str, body: dict,
    ) -> dict:
        chapter, row, delta, items, model_cls = await self._editable_delta(
            user, project_id, chapter_no, category
        )
        validated = self._validate_delta(model_cls, body)
        if validated.entity_key != entity_key:
            raise DomainError("본문 entity_key가 경로와 일치하지 않습니다.")
        idx = next(
            (i for i, it in enumerate(items) if it.get("entity_key") == entity_key), None
        )
        if idx is None:
            raise NotFoundError(f"'{entity_key}' 항목을 찾을 수 없습니다.")
        items[idx] = validated.model_dump()
        await self._persist_delta(chapter, row, delta, category, items)
        logger.info("delta updated: project=%s ch=%s %s/%s", project_id, chapter_no, category, entity_key)
        return validated.model_dump()

    async def add_delta_item(
        self, user: User, project_id: uuid.UUID, chapter_no: int,
        category: str, body: dict,
    ) -> dict:
        chapter, row, delta, items, model_cls = await self._editable_delta(
            user, project_id, chapter_no, category
        )
        validated = self._validate_delta(model_cls, body)
        if any(it.get("entity_key") == validated.entity_key for it in items):
            raise ConflictError(f"'{validated.entity_key}' 항목이 이미 있습니다.")
        items.append(validated.model_dump())
        await self._persist_delta(chapter, row, delta, category, items)
        logger.info("delta added: project=%s ch=%s %s/%s", project_id, chapter_no, category, validated.entity_key)
        return validated.model_dump()

    async def delete_delta_item(
        self, user: User, project_id: uuid.UUID, chapter_no: int,
        category: str, entity_key: str,
    ) -> None:
        chapter, row, delta, items, _ = await self._editable_delta(
            user, project_id, chapter_no, category
        )
        remaining = [it for it in items if it.get("entity_key") != entity_key]
        if len(remaining) == len(items):
            raise NotFoundError(f"'{entity_key}' 항목을 찾을 수 없습니다.")
        await self._persist_delta(chapter, row, delta, category, remaining)
        logger.info("delta deleted: project=%s ch=%s %s/%s", project_id, chapter_no, category, entity_key)

    # ── 저장하기 (캐논 병합, 트랜잭션 안에서 딱 한 번) ──────────
    async def save(
        self, user: User, project_id: uuid.UUID, chapter_no: int
    ) -> SaveResult:
        chapter = await self._owned_chapter(user, project_id, chapter_no)
        return await self.save_chapter(chapter)

    async def save_chapter(self, chapter: Chapter) -> SaveResult:
        """저장 본체 — 소유권 검사 없이 chapter 를 받는다. API save 와 워커 자동 저장이 공유.

        캐논 병합 + status=saved 를 한 트랜잭션에서(불변원칙 3). 회차 행을 잠근 뒤
        상태를 다시 보므로, 동시에 두 번 불려도 병합은 한 번이고 나머지는 멱등 반환.
        """
        locked = await self.chapters.lock(chapter.id)
        if locked is None:
            raise NotFoundError(f"{chapter.chapter_no}화를 찾을 수 없습니다.")
        chapter = locked
        chapter_no = chapter.chapter_no

        # 멱등: 이미 저장됐으면 그대로 반환(중복 병합 방지)
        if chapter.status == ChapterStatus.saved.value:
            await self.s.commit()  # 잠금 해제 (변경 없음)
            return SaveResult(chapter_no=chapter_no, status=chapter.status)

        if chapter.status != ChapterStatus.reviewed.value:
            await self.s.commit()  # 잠금 해제 (변경 없음)
            raise ConflictError("분석이 완료된(reviewed) 회차만 저장할 수 있습니다.")

        row = await self.analysis.get_latest(chapter.id)
        if row is None or row.canon_delta is None:
            await self.s.commit()  # 잠금 해제 (변경 없음)
            raise ConflictError("저장할 분석 결과가 없습니다.")

        # 캐논 병합 + 상태 전환을 같은 트랜잭션에서 (불변원칙 3)
        await CanonService(self.s).merge_delta(
            project_id=chapter.project_id,
            canon_delta=row.canon_delta,
            source_chapter=chapter_no,
        )
        chapter.status = ChapterStatus.saved.value
        await self._touch_project(chapter.project_id)
        await self.s.commit()
        logger.info(
            "chapter saved + canon merged: project=%s ch=%s", chapter.project_id, chapter_no
        )
        return SaveResult(chapter_no=chapter_no, status=ChapterStatus.saved.value)
