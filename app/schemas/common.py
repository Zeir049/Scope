"""공통 응답 스키마. 페이지네이션 형태는 계약서 0장대로 통일."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    total_pages: int
    total_count: int


class MessageResponse(BaseModel):
    message: str
