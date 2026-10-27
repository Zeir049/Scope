"""파일 저장 경계. STORAGE_MODE로 구현 주입(지금은 로컬 디스크).

S3 등은 S3Storage를 추가하고 factory에 한 줄 더하면 교체된다.
반환값은 외부에서 접근 가능한 URL/경로(여기선 /uploads/... 정적 경로).
"""
from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class Storage(Protocol):
    async def save(self, data: bytes, *, subdir: str, filename: str) -> str:
        """파일을 저장하고 접근 URL(경로)을 반환."""
        ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    async def save(self, data: bytes, *, subdir: str, filename: str) -> str:
        safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
        target_dir = self.root / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / safe_name).write_bytes(data)
        # main.py가 self.root를 /uploads 로 정적 마운트한다.
        url = f"/uploads/{subdir}/{safe_name}"
        logger.info("stored file: %s (%d bytes)", url, len(data))
        return url


@lru_cache
def get_storage() -> Storage:
    mode = settings.storage_mode.lower()
    if mode == "local":
        return LocalStorage(settings.upload_dir)
    # if mode == "s3": return S3Storage(...)
    raise ValueError(f"알 수 없는 STORAGE_MODE: {settings.storage_mode}")
