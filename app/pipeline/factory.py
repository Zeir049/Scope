"""PIPELINE_MODE 설정으로 파이프라인 구현을 주입 (CLAUDE.md 불변원칙 1).

서비스 코드는 get_pipeline()이 돌려주는 AnalysisPipeline 추상에만 의존한다.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.pipeline.interface import AnalysisPipeline


@lru_cache
def get_pipeline() -> AnalysisPipeline:
    mode = settings.pipeline_mode.lower()
    if mode == "fake":
        from app.pipeline.fake import FakePipeline

        return FakePipeline()
    if mode == "remote":
        from app.pipeline.remote import RemotePipeline

        return RemotePipeline(settings.pipeline_remote_url)
    if mode == "local":
        from app.pipeline.local import LocalPipeline

        return LocalPipeline()
    if mode == "replay":
        from app.pipeline.replay import ReplayPipeline

        return ReplayPipeline(delay_seconds=settings.replay_delay_seconds)
    raise ValueError(f"알 수 없는 PIPELINE_MODE: {settings.pipeline_mode}")
