"""라우터 공통 업로드 처리: 상한까지만 읽기, 이미지 바이트 확인.

회차 원고(chapters.py)와 프로젝트 썸네일(projects.py)이 함께 쓴다.
HTTP 경계의 입력 검증이라 api 레이어에 둔다(비즈니스 로직 아님).
"""
from __future__ import annotations

from fastapi import UploadFile

from app.core.exceptions import DomainError


def _human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n // (1024 * 1024)}MB"
    if n >= 1024:
        return f"{n // 1024}KB"
    return f"{n}B"


async def read_upload_limited(upload: UploadFile, limit: int) -> bytes:
    """업로드 파일을 limit 바이트까지만 읽는다 — 초과 시 400 (메모리 소진 방지)."""
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise DomainError(f"파일이 너무 큽니다. 최대 {_human_size(limit)}까지 올릴 수 있습니다.")
    return content


def looks_like_image(data: bytes) -> bool:
    """실제 바이트가 PNG/JPEG/GIF/WebP 인지 매직 바이트로 확인한다(Content-Type 은 믿지 않는다)."""
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )
