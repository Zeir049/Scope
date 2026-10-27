"""회차 요청/응답 스키마 (계약서 3장)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class ChapterCreate(BaseModel):
    """텍스트 업로드(방법 B) JSON 바디. 파일 업로드(방법 A)는 multipart로 별도 처리."""

    chapter_no: int = Field(gt=0)
    title: str | None = None
    text: str = Field(min_length=1)
    kind: str = "narrative"  # narrative | rules


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chapter_no: int
    title: str | None
    status: str
    created_at: dt.datetime | None = None  # 프론트 회차 기록 날짜 표시용
    kind: str = "narrative"
    updated_at: dt.datetime | None = None


class ChapterDetailOut(BaseModel):
    """회차 상세 (원문 포함). 목록(ChapterOut)에는 raw_text 를 넣지 않는다."""

    chapter_no: int
    title: str | None
    kind: str
    status: str
    raw_text: str | None
    raw_path: str | None
    content_hash: str | None
    created_at: dt.datetime | None
    updated_at: dt.datetime | None
    failed_stage: str | None = None   # 실패 시 extract|review
    failed_detail: str | None = None  # 실패 사유
    contradiction_count: int = 0


class ChapterListOut(BaseModel):
    items: list[ChapterOut]
