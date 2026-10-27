"""공유 링크 스키마. (ENABLE_SHARING)"""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.chapter import ChapterOut
from app.schemas.project import ProjectOut


class ShareLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    token: str
    url: str
    revoked: bool
    created_at: dt.datetime


class SharedProjectOut(BaseModel):
    """공개 링크로 보는 읽기전용 뷰."""

    project: ProjectOut
    chapters: list[ChapterOut]
