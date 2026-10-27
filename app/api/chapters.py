"""회차 라우터 (계약서 3장). 업로드는 multipart(파일) / JSON(텍스트) 둘 다 지원."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._upload import read_upload_limited
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_session
from app.core.exceptions import DomainError
from app.models import User
from app.parsing.registry import parse as parse_document
from app.schemas.analysis import (
    AnalyzeAccepted,
    ContradictionItem,
    ContradictionStatusUpdate,
    ResultOut,
    ReviewRequest,
    SaveResult,
    VisualOut,
)
from app.schemas.chapter import (
    ChapterCreate,
    ChapterDetailOut,
    ChapterListOut,
    ChapterOut,
)
from app.service.chapter_service import ChapterService
from app.workers.queue import enqueue_analysis

router = APIRouter(prefix="/projects/{project_id}/chapters", tags=["chapters"])


@router.get("", response_model=ChapterListOut)
async def list_chapters(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChapterListOut:
    return await ChapterService(session).list_chapters(user, project_id)


@router.post("", response_model=ChapterOut, status_code=201)
async def upload_chapter(
    project_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChapterOut:
    """방법 A) multipart/form-data: file, chapter_no, title, kind
    방법 B) application/json: { chapter_no, title, text, kind }
    kind = narrative(기본) | rules. 같은 원문이 이미 있으면 409 + existing_chapter_no.
    """
    content_type = request.headers.get("content-type", "")
    title: str | None
    raw_path: str | None = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_no = form.get("chapter_no")
        title = form.get("title") or None
        kind = str(form.get("kind") or "narrative")
        upload = form.get("file")
        if raw_no is None:
            raise DomainError("chapter_no는 필수입니다.")
        try:
            chapter_no = int(raw_no)  # type: ignore[arg-type]
        except (TypeError, ValueError) as e:
            raise DomainError("chapter_no는 정수여야 합니다.") from e
        if chapter_no <= 0:
            raise DomainError("chapter_no는 1 이상이어야 합니다.")
        text: str | None = None
        if upload is not None and hasattr(upload, "read"):
            content = await read_upload_limited(upload, settings.max_upload_bytes)
            raw_path = getattr(upload, "filename", None)
            # 확장자별 파서 레지스트리로 텍스트 추출(txt/md/docx, 추후 확장 용이)
            text = parse_document(raw_path, content)
        if not text:
            raise DomainError("파일(file) 또는 텍스트(text)가 필요합니다.")
    else:
        try:
            data = await request.json()
        except Exception as e:  # noqa: BLE001 - 잘못된 JSON
            raise DomainError("요청 본문(JSON) 형식이 올바르지 않습니다.") from e
        try:
            body = ChapterCreate.model_validate(data)
        except ValidationError as e:
            raise DomainError(f"입력값 오류: {e.errors()[0]['msg']}") from e
        chapter_no = body.chapter_no
        title = body.title
        text = body.text
        kind = body.kind

    return await ChapterService(session).upload(
        user=user,
        project_id=project_id,
        chapter_no=chapter_no,
        title=title,
        text=text,
        raw_path=raw_path,
        kind=kind,
    )


@router.get("/{chapter_no}", response_model=ChapterDetailOut)
async def get_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChapterDetailOut:
    """회차 상세(원문 포함 + 실패 사유 + 모순 수)."""
    return await ChapterService(session).get_detail(user, project_id, chapter_no)


@router.delete("/{chapter_no}", status_code=204)
async def delete_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """회차 삭제. saved 또는 분석 진행 중(extracting/reviewing)이면 409."""
    await ChapterService(session).delete(user, project_id, chapter_no)
    return Response(status_code=204)


@router.put("/{chapter_no}", response_model=ChapterOut)
async def reupload_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChapterOut:
    """회차 원고 교체(재업로드) — 수정 원고를 같은 회차로 다시 분석하는 진입점.

    POST와 같은 두 방식(multipart: file/title/kind | JSON: {title, text, kind}) 지원,
    chapter_no는 경로에서. 상태는 uploaded로 돌아가고 이전 분석 결과는 정리된다.
    kind 를 안 보내면 기존 값 유지. 중복 원문이어도 거절하지 않는다(해시만 갱신).
    """
    content_type = request.headers.get("content-type", "")
    title: str | None
    text: str | None
    kind: str | None
    raw_path: str | None = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        title = form.get("title") or None
        kind = str(form["kind"]) if form.get("kind") else None
        text = None
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            content = await read_upload_limited(upload, settings.max_upload_bytes)
            raw_path = getattr(upload, "filename", None)
            text = parse_document(raw_path, content)
    else:
        try:
            data = await request.json()
        except Exception as e:  # noqa: BLE001 - 잘못된 JSON
            raise DomainError("요청 본문(JSON) 형식이 올바르지 않습니다.") from e
        title = data.get("title")
        text = data.get("text")
        kind = data.get("kind")

    return await ChapterService(session).update_content(
        user=user,
        project_id=project_id,
        chapter_no=chapter_no,
        title=title,
        text=text,
        raw_path=raw_path,
        kind=kind,
    )


@router.post("/{chapter_no}/extract", response_model=AnalyzeAccepted, status_code=202)
async def extract_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalyzeAccepted:
    """1차 추출 시작(비동기). 202 후 프론트는 result를 폴링(extracting→extracted)."""
    accepted = await ChapterService(session).start_extraction(
        user, project_id, chapter_no
    )
    await enqueue_analysis("extract", project_id, chapter_no)
    return accepted


@router.post("/{chapter_no}/review", response_model=AnalyzeAccepted, status_code=202)
async def review_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    body: ReviewRequest | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalyzeAccepted:
    """2차 검수 시작(비동기). extracted 또는 saved(재검수)에서. 202 후 폴링.

    auto_save(기본 true)면 reviewing → reviewed → saved 까지 서버가 진행한다.
    false 면 reviewed 에서 멈추고 POST .../save 로 저장한다.
    """
    opts = body or ReviewRequest()
    accepted = await ChapterService(session).start_review(
        user, project_id, chapter_no
    )
    await enqueue_analysis("review", project_id, chapter_no, auto_save=opts.auto_save)
    return accepted


@router.post("/{chapter_no}/analyze", response_model=AnalyzeAccepted, status_code=202)
async def analyze_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalyzeAccepted:
    """편의 API: 추출→검수를 한 번에 연속 실행(비동기). 폴링으로 reviewed까지 관찰."""
    accepted = await ChapterService(session).start_analysis(
        user, project_id, chapter_no
    )
    await enqueue_analysis("full", project_id, chapter_no)
    return accepted


@router.get(
    "/{chapter_no}/result",
    response_model=ResultOut,
    response_model_exclude_none=True,
)
async def get_result(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResultOut:
    """진행상황/결과 폴링. status에 따라 채워지는 필드가 다르다(계약서 3장)."""
    return await ChapterService(session).get_result(user, project_id, chapter_no)


@router.get("/{chapter_no}/visual", response_model=VisualOut)
async def get_visual(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VisualOut:
    """회차별 시각화 원본 JSON(LLM prompt_result_1 포맷). 없으면 visual=null."""
    return await ChapterService(session).get_visual(user, project_id, chapter_no)


@router.post("/{chapter_no}/save", response_model=SaveResult)
async def save_chapter(
    project_id: uuid.UUID,
    chapter_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SaveResult:
    """[저장하기] → 현재 회차 분석 결과를 캐논에 병합(commit)."""
    return await ChapterService(session).save(user, project_id, chapter_no)


@router.patch(
    "/{chapter_no}/contradictions/{contradiction_id}",
    response_model=ContradictionItem,
)
async def update_contradiction_status(
    project_id: uuid.UUID,
    chapter_no: int,
    contradiction_id: uuid.UUID,
    body: ContradictionStatusUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ContradictionItem:
    """모순 판정(✓ confirmed / ✕ dismissed / pending 되돌리기). 갱신된 항목 반환."""
    return await ChapterService(session).update_contradiction_status(
        user, project_id, chapter_no, contradiction_id, body
    )


# ── 추출 결과 항목 편집 (extracted/reviewed 상태, save 전) ─────────────
# category = worldview|characters|relations|timeline|spaces|events|foreshadowing
# 본문은 category별 Delta 모델로 service에서 Pydantic 검증(잘못되면 400).


@router.patch("/{chapter_no}/delta/{category}/{entity_key}")
async def update_delta_item(
    project_id: uuid.UUID,
    chapter_no: int,
    category: str,
    entity_key: str,
    body: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """추출 항목 1개 수정. 갱신된 Delta를 반환."""
    return await ChapterService(session).update_delta_item(
        user, project_id, chapter_no, category, entity_key, body
    )


@router.post("/{chapter_no}/delta/{category}", status_code=201)
async def add_delta_item(
    project_id: uuid.UUID,
    chapter_no: int,
    category: str,
    body: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """추출 항목 1개 추가. 생성된 Delta를 반환."""
    return await ChapterService(session).add_delta_item(
        user, project_id, chapter_no, category, body
    )


@router.delete("/{chapter_no}/delta/{category}/{entity_key}", status_code=204)
async def delete_delta_item(
    project_id: uuid.UUID,
    chapter_no: int,
    category: str,
    entity_key: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """추출 항목 1개 삭제."""
    await ChapterService(session).delete_delta_item(
        user, project_id, chapter_no, category, entity_key
    )
