"""시연용 리플레이 파이프라인. 회차 번호별로 미리 준비한 AI 응답을 그대로 돌려준다.

AI 파트 실행 결과(인셉션 각본 분석 + 심은 모순 검수)를 1·2·3화로 나눈 자료가
replay_data/chapter_N.json 에 있다(scripts/build_replay_data.py 가 만든다). 각 파일은
AI 서버 /extract 응답(visual, rich JSON)과 /review 응답(contradictions)을 담는다.
그래서 이 구현은 RemotePipeline 이 AI 서버 응답을 받은 뒤와 같은 경로를 탄다 —
visual → visual_to_canon_delta 변환, 원본은 visual_json 으로 보존.

업로드할 원문은 replay_data/chapter_N.txt. 다른 글을 올리면 결과는 그대로 나오되
모순 인용 위치(span)가 맞지 않으므로 경고 로그를 남긴다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from app.pipeline.interface import (
    CanonDelta,
    CanonSnapshot,
    ExtractionOutput,
    PipelineHealth,
    ReviewOutput,
)
from app.pipeline.transform import visual_to_canon_delta

logger = logging.getLogger(__name__)

REPLAY_DIR = Path(__file__).parent / "replay_data"


def text_fingerprint(text: str) -> str:
    """원문 비교용 지문. 공백·줄바꿈 차이(붙여넣기·끝 줄바꿈)는 같은 글로 본다."""
    return hashlib.sha1("".join(text.split()).encode("utf-8")).hexdigest()


class ReplayPipeline:
    """AnalysisPipeline 프로토콜 구현(리플레이) — 2단계(추출/검수)."""

    def __init__(self, delay_seconds: float = 0.0, data_dir: Path = REPLAY_DIR) -> None:
        self.delay_seconds = delay_seconds
        self.data_dir = data_dir

    def _chapters(self) -> list[int]:
        return sorted(int(p.stem.split("_")[1]) for p in self.data_dir.glob("chapter_*.json"))

    def _load(self, chapter_no: int | None, chapter_text: str) -> dict:
        path = self.data_dir / f"chapter_{chapter_no}.json"
        if chapter_no is None or not path.is_file():
            raise ValueError(
                f"리플레이 자료가 없는 회차입니다: {chapter_no}화 (준비된 회차: {self._chapters()})"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        if text_fingerprint(chapter_text) != data.get("text_sha1"):
            logger.warning(
                "replay: %s화 원문이 %s 와 다름 — 결과는 그대로 쓰지만 모순 인용 위치가 맞지 않을 수 있음",
                chapter_no, path.with_suffix(".txt").name,
            )
        return data

    async def health(self) -> PipelineHealth:
        chapters = self._chapters()
        if not chapters:
            return PipelineHealth(ok=False, mode="replay", message="리플레이 자료가 없습니다.")
        return PipelineHealth(
            ok=True, mode="replay", message=f"리플레이 파이프라인 (준비된 회차: {chapters})"
        )

    async def extract_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ExtractionOutput:
        await asyncio.sleep(self.delay_seconds)
        visual = self._load(chapter_no, chapter_text)["visual"]
        logger.info("replay extract: ch=%s", chapter_no)
        return ExtractionOutput(
            highlighted_text=chapter_text,
            canon_delta=visual_to_canon_delta(visual),
            visual_json=visual,
        )

    async def review_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        delta: CanonDelta,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ReviewOutput:
        await asyncio.sleep(self.delay_seconds)
        data = self._load(chapter_no, chapter_text)
        logger.info("replay review: ch=%s contradictions=%d", chapter_no, len(data["contradictions"]))
        return ReviewOutput.model_validate({"contradictions": data["contradictions"]})
