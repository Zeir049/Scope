"""프로젝트 요청/응답 스키마 (계약서 2장)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    # 비어 있거나 없으면 서버가 Project_N 을 붙인다
    name: str | None = None
    author: str | None = None  # 미지정 시 서비스가 로그인 사용자 이름으로 채운다


class ProjectUpdate(BaseModel):
    """부분 수정. 보낸 필드만 변경된다(None = 변경 안 함)."""

    name: str | None = Field(default=None, min_length=1)
    author: str | None = None
    description: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    author: str | None
    thumbnail_url: str | None
    description: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    chapter_count: int = 0
    last_chapter_status: str | None = None  # 가장 큰 chapter_no 회차의 status
