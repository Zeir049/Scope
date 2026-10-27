"""프로젝트 수정 + 썸네일 업로드 테스트."""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.config import settings
from app.core.db import SessionLocal
from app.repository.project_repo import ProjectRepository


async def test_patch_project(client: AsyncClient, auth_headers: dict, project_id: str):
    r = await client.patch(
        f"/projects/{project_id}",
        json={"author": "Cho", "description": "정직한 나무꾼"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["author"] == "Cho" and body["description"] == "정직한 나무꾼"


async def test_patch_ownership(client: AsyncClient, auth_headers: dict, project_id: str):
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = await client.patch(f"/projects/{project_id}", json={"author": "x"}, headers=h2)
    assert r.status_code == 403


# 실제 이미지 매직 바이트(머리만 검사한다 — 디코딩은 하지 않는다)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def test_thumbnail_upload(client: AsyncClient, auth_headers: dict, project_id: str):
    r = await client.post(
        f"/projects/{project_id}/thumbnail",
        files={"file": ("t.png", PNG_BYTES, "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["thumbnail_url"].startswith("/uploads/thumbnails/")

    async with SessionLocal() as s:
        project = await ProjectRepository(s).get_by_id(uuid.UUID(project_id))
        assert project.thumbnail_url


async def test_thumbnail_rejects_non_image(client: AsyncClient, auth_headers: dict, project_id: str):
    r = await client.post(
        f"/projects/{project_id}/thumbnail",
        files={"file": ("t.txt", b"not an image", "text/plain")},
        headers=auth_headers,
    )
    assert r.status_code == 400


async def test_thumbnail_rejects_non_image_bytes(client: AsyncClient, auth_headers: dict, project_id: str):
    # Content-Type 만 image/png 이고 실제 바이트는 이미지가 아니면 400
    r = await client.post(
        f"/projects/{project_id}/thumbnail",
        files={"file": ("t.png", b"<html>not really a png</html>", "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 400


async def test_thumbnail_accepts_jpeg_gif_webp(client: AsyncClient, auth_headers: dict, project_id: str):
    samples = {
        "t.jpg": (b"\xff\xd8\xff\xe0" + b"\x00" * 16, "image/jpeg"),
        "t.gif": (b"GIF89a" + b"\x00" * 16, "image/gif"),
        "t.webp": (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16, "image/webp"),
    }
    for name, (data, ctype) in samples.items():
        r = await client.post(
            f"/projects/{project_id}/thumbnail", files={"file": (name, data, ctype)}, headers=auth_headers
        )
        assert r.status_code == 200, name


async def test_thumbnail_size_limit(client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch):
    monkeypatch.setattr(settings, "max_thumbnail_bytes", 64)
    r = await client.post(
        f"/projects/{project_id}/thumbnail",
        files={"file": ("big.png", PNG_BYTES + b"\x00" * 64, "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 400 and "너무 큽니다" in r.text

    # 상한 이내는 정상
    r = await client.post(
        f"/projects/{project_id}/thumbnail",
        files={"file": ("ok.png", PNG_BYTES, "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 200
