"""도메인 예외 + 전역 핸들러.

라우터/서비스는 도메인 예외만 던지고, HTTP 매핑은 여기서 한 번에 한다
(CLAUDE.md: 라우터에서 try/except 남발 금지). 응답 형태는 계약서대로
항상 { "detail": "..." } 형태. 클라이언트가 분기에 쓸 값이 더 필요하면
extra 로 최상위 필드를 덧붙인다(예: 중복 업로드 409 의 existing_chapter_no).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """모든 도메인 예외의 베이스."""

    status_code: int = 400

    def __init__(self, detail: str, extra: dict | None = None) -> None:
        self.detail = detail
        self.extra = extra or {}
        super().__init__(detail)


class NotFoundError(DomainError):
    status_code = 404


class PermissionDeniedError(DomainError):
    status_code = 403


class ConflictError(DomainError):
    status_code = 409


class AuthError(DomainError):
    status_code = 401


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={**exc.extra, "detail": exc.detail}
        )
