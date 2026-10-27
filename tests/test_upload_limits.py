"""업로드 크기 제한 테스트 — 공개 터널에서 대용량 입력으로 서버가 소진되지 않게.

- 파일 바이트 상한(max_upload_bytes) 초과 → 400
- 텍스트 길이 상한(max_chapter_chars) 초과 → 400 (POST/PUT 모두)
- 상한 이내는 정상
"""
from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings


async def test_upload_size_limits(client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch):
    h, pid = auth_headers, project_id
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    monkeypatch.setattr(settings, "max_chapter_chars", 100)

    # 파일 상한 초과 (multipart)
    r = await client.post(
        f"/projects/{pid}/chapters",
        data={"chapter_no": "1"},
        files={"file": ("big.txt", b"x" * 2048, "text/plain")},
        headers=h,
    )
    assert r.status_code == 400 and "너무 큽니다" in r.text

    # 텍스트 상한 초과 (JSON)
    r = await client.post(
        f"/projects/{pid}/chapters",
        json={"chapter_no": 1, "text": "가" * 101},
        headers=h,
    )
    assert r.status_code == 400 and "너무 깁니다" in r.text

    # 상한 이내는 정상
    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "가" * 100}, headers=h
    )
    assert r.status_code == 201

    # PUT 재업로드도 두 상한 모두 적용
    r = await client.put(f"/projects/{pid}/chapters/1", json={"text": "가" * 101}, headers=h)
    assert r.status_code == 400
    r = await client.put(
        f"/projects/{pid}/chapters/1",
        files={"file": ("big.txt", b"x" * 2048, "text/plain")},
        headers=h,
    )
    assert r.status_code == 400 and "너무 큽니다" in r.text
