"""진행 중 분석 작업 조회 스키마 (D7: chapters.status 에서 파생 — 별도 저장 없음)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class ActiveJob(BaseModel):
    project_id: uuid.UUID
    project_name: str
    chapter_no: int
    title: str | None
    status: str  # extracting | reviewing
    progress: int | None = None  # analysis_results.progress (0~100)
    started_at: dt.datetime | None  # = chapters.updated_at (진행 상태로 바뀐 시각)
    stale: bool  # ANALYSIS_STALE_MINUTES 초과 — 표시용(여기서 failed 로 바꾸지 않는다)


class ActiveJobsOut(BaseModel):
    items: list[ActiveJob]
