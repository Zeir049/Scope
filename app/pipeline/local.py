"""구현 B — 몸통과 같은 프로세스에서 파이프라인을 직접 실행하는 어댑터 (스켈레톤).

모순검출 LLM 로직을 같은 프로세스에 붙일 때 여기를 채운다. 모순검출 내부
로직 자체는 이 코드베이스의 책임이 아니다(별도 영역) — interface 계약만 만족시키면 된다.
"""
from __future__ import annotations

from app.pipeline.interface import (
    CanonDelta,
    CanonSnapshot,
    ExtractionOutput,
    PipelineHealth,
    ReviewOutput,
)

_NOT_READY = (
    "LocalPipeline은 아직 구현되지 않았습니다. "
    "PIPELINE_MODE=fake 로 개발하거나 remote 어댑터를 사용하세요."
)


class LocalPipeline:
    async def health(self) -> PipelineHealth:
        return PipelineHealth(ok=False, mode="local", message=_NOT_READY)

    async def extract_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ExtractionOutput:
        raise NotImplementedError(_NOT_READY)

    async def review_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        delta: CanonDelta,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ReviewOutput:
        raise NotImplementedError(_NOT_READY)
