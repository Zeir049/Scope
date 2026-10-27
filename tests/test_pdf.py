"""pdf 업로드 파싱 테스트.

외부 라이브러리 없이, 텍스트 레이어가 있는 최소 PDF를 손으로 만들어 업로드한다.
(Helvetica 표준폰트라 본문은 ASCII로 둔다 — 한글은 폰트/인코딩 별도 영역.)
"""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.repository.chapter_repo import ChapterRepository


def _make_pdf(text: str) -> bytes:
    """단일 페이지 + 텍스트 1줄짜리 유효한 PDF 바이트(정확한 xref 오프셋 계산)."""
    stream = b"BT /F1 18 Tf 20 120 Td (" + text.encode("latin-1") + b") Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return bytes(out)


async def test_pdf_upload_extracts_text(client: AsyncClient, auth_headers: dict, project_id: str):
    pdf = _make_pdf("Axe story first line")
    r = await client.post(
        f"/projects/{project_id}/chapters",
        data={"chapter_no": "1", "title": "1화"},
        files={"file": ("ch1.pdf", pdf, "application/pdf")},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    async with SessionLocal() as s:
        chapter = await ChapterRepository(s).get(uuid.UUID(project_id), 1)
        assert "Axe story first line" in (chapter.raw_text or "")


async def test_pdf_without_text_layer_400(client: AsyncClient, auth_headers: dict, project_id: str):
    """텍스트 레이어가 없는(깨진/빈) PDF → 400 안내."""
    r = await client.post(
        f"/projects/{project_id}/chapters",
        data={"chapter_no": "2"},
        files={"file": ("scan.pdf", b"%PDF-1.4\n%broken", "application/pdf")},
        headers=auth_headers,
    )
    assert r.status_code == 400
