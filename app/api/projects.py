"""프로젝트 라우터 (계약서 2장)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._upload import looks_like_image, read_upload_limited
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_session
from app.core.exceptions import DomainError
from app.models import User
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.service.project_service import ProjectService
from app.storage.storage import get_storage

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectOut]:
    """page_size 기본 20, 1~50 (범위 밖이면 400). 항목에 chapter_count/last_chapter_status 포함."""
    return await ProjectService(session).list_projects(user, page, q, page_size)


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    return await ProjectService(session).create(user, body)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    return await ProjectService(session).get(user, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    return await ProjectService(session).update(user, project_id, body)


@router.post("/{project_id}/thumbnail", response_model=ProjectOut)
async def upload_thumbnail(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    if not (file.content_type or "").startswith("image/"):
        raise DomainError("이미지 파일만 업로드할 수 있습니다.")
    data = await read_upload_limited(file, settings.max_thumbnail_bytes)
    if not looks_like_image(data):
        raise DomainError("이미지 파일만 업로드할 수 있습니다. (PNG·JPEG·GIF·WebP)")
    url = await get_storage().save(
        data, subdir="thumbnails", filename=file.filename or "thumb"
    )
    return await ProjectService(session).set_thumbnail(user, project_id, url)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await ProjectService(session).delete(user, project_id)
    return Response(status_code=204)
