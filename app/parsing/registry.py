"""원문 파일 파서 레지스트리. 확장자 → 파서 함수.

새 포맷 추가 = @register("pdf") 데코레이터로 함수 하나 등록하면 끝.
제거 = 해당 함수 삭제. 코어 코드는 안 건드린다.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.exceptions import DomainError

logger = logging.getLogger(__name__)

# 확장자(소문자, 점 없음) → bytes를 text로 변환하는 함수
Parser = Callable[[bytes], str]
_REGISTRY: dict[str, Parser] = {}


def register(*exts: str) -> Callable[[Parser], Parser]:
    def deco(fn: Parser) -> Parser:
        for ext in exts:
            _REGISTRY[ext.lower()] = fn
        return fn

    return deco


def supported_exts() -> list[str]:
    return sorted(_REGISTRY)


def parse(filename: str | None, content: bytes) -> str:
    """파일명 확장자로 파서를 골라 텍스트 추출. 미지원 확장자면 400."""
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[1].lower()
    parser = _REGISTRY.get(ext)
    if parser is None:
        raise DomainError(
            f"지원하지 않는 파일 형식입니다(.{ext or '?'}). "
            f"가능: {', '.join('.' + e for e in supported_exts())}"
        )
    return parser(content)


# ── 기본 파서들 등록 ──────────────────────────────────────
@register("txt", "md")
def _parse_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


@register("docx")
def _parse_docx(content: bytes) -> str:
    import io

    try:
        import docx  # python-docx
    except ImportError as e:  # 의존성 없으면 명확히 안내
        raise DomainError(
            ".docx 파싱에는 python-docx가 필요합니다. (pip install python-docx)"
        ) from e

    document = docx.Document(io.BytesIO(content))
    return "\n".join(p.text for p in document.paragraphs)


@register("pdf")
def _parse_pdf(content: bytes) -> str:
    import io

    try:
        from pypdf import PdfReader
    except ImportError as e:  # 의존성 없으면 명확히 안내
        raise DomainError(
            ".pdf 파싱에는 pypdf가 필요합니다. (pip install pypdf)"
        ) from e

    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:  # noqa: BLE001 - 손상/암호화 PDF 등은 400으로 안내
        raise DomainError(f"PDF를 읽지 못했습니다: {e}") from e

    if not text.strip():
        # 스캔 이미지 PDF(텍스트 레이어 없음) 등 — OCR은 별도 영역
        raise DomainError(
            "PDF에서 텍스트를 추출하지 못했습니다. "
            "(스캔 이미지 PDF는 텍스트 레이어가 없어 지원하지 않습니다)"
        )
    return text
