"""개발용 가짜 파이프라인. 고정/결정적 결과를 반환해 몸통부터 완성 가능.

진짜 LLM 파이프라인은 나중에 RemotePipeline/LocalPipeline으로 갈아끼운다
(PIPELINE_MODE 설정). 이 Fake는 실제 LLM이 내려줄 rich JSON 예시
(fake_visual.json — prompt_result_1 포맷, '헤일트라움' 샘플)를 그대로 반환해서
rich JSON 경로(변환→raw_output 보존→visual API)를 실전과 동일하게 태운다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from app.pipeline.interface import (
    CanonDelta,
    CanonSnapshot,
    ConflictRef,
    ContradictionOut,
    ExtractionOutput,
    PipelineHealth,
    ReviewOutput,
    Span,
    WorldviewDelta,
)
from app.pipeline.transform import visual_to_canon_delta

# 각 단계에 걸리는 시간을 흉내 → 프론트의 폴링(extracting→extracted, reviewing→reviewed)을
# 실제로 테스트 가능.
FAKE_DELAY_SECONDS = 1.0

# 실제 LLM 응답 예시(회차 원문과 무관한 고정 샘플). 모듈 로드 시 1회 읽는다.
_FAKE_VISUAL: dict = json.loads(
    (Path(__file__).parent / "fake_visual.json").read_text(encoding="utf-8")
)


class FakePipeline:
    """AnalysisPipeline 프로토콜 구현(가짜) — 2단계(추출/검수)."""

    async def health(self) -> PipelineHealth:
        # 외부 의존이 없으니 항상 준비돼 있다.
        return PipelineHealth(ok=True, mode="fake", message="가짜 파이프라인 (분석 결과는 고정 예시)")

    async def extract_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ExtractionOutput:
        # 1차 추출: 6기준 구조화 데이터만. 모순 판정은 하지 않는다.
        await asyncio.sleep(FAKE_DELAY_SECONDS)
        # [규칙] 문서는 서사가 아니라 사용자가 직접 쓴 설정 목록 — 지어낸 예시
        # 델타 대신 본문을 줄 단위로 파싱해 그대로 세계관 규칙에 반영한다.
        if (title or "").startswith("[규칙]"):
            return ExtractionOutput(
                highlighted_text=chapter_text,
                canon_delta=self._rules_canon_delta(chapter_text),
            )
        # 일반 회차: 실제 LLM처럼 rich JSON을 주는 상황을 재현 — 원본은
        # visual_json으로 보존되고, 캐논 병합에는 변환된 델타가 쓰인다.
        return ExtractionOutput(
            highlighted_text=chapter_text,
            canon_delta=visual_to_canon_delta(_FAKE_VISUAL),
            visual_json=_FAKE_VISUAL,
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
        # 2차 검수: 기존 캐논이 있을 때만 '충돌'을 만들어 누적 대조를 흉내낸다.
        await asyncio.sleep(FAKE_DELAY_SECONDS)
        # [규칙] 문서는 사용자가 확정한 설정이므로 가짜 충돌을 만들지 않는다.
        if (title or "").startswith("[규칙]"):
            return ReviewOutput(contradictions=[])
        return ReviewOutput(
            contradictions=self._fake_contradictions(chapter_text, canon)
        )

    @staticmethod
    def _rules_canon_delta(text: str) -> CanonDelta:
        """규칙 문서 본문 → 줄 단위 세계관 규칙. 같은 문장은 같은 key라 재저장은 멱등."""
        rules = []
        for raw in (text or "").splitlines():
            line = re.sub(r"^\s*(?:[-*•·]|\d+[.)])\s*", "", raw).strip()  # 불릿/번호 제거
            if not line:
                continue
            key = "rule-" + hashlib.sha1(line.encode("utf-8")).hexdigest()[:10]
            rules.append(
                WorldviewDelta(entity_key=key, item=line, detail="사용자 정의 규칙")
            )
        return CanonDelta(worldview=rules)

    @staticmethod
    def _fake_contradictions(
        text: str, canon: CanonSnapshot
    ) -> list[ContradictionOut]:
        # 기존 캐논이 있을 때만 '충돌'을 만들어낸다(누적 대조 흉내).
        prior_chapters = [
            e.get("source_chapter")
            for e in (canon.characters + canon.worldview)
            if e.get("source_chapter")
        ]
        if not prior_chapters:
            return []
        ref_chapter = min(prior_chapters)
        end = min(24, len(text)) or 1
        return [
            ContradictionOut(
                span=Span(start=0, end=end, quote=text[:end]),
                conflict_ref=ConflictRef(
                    chapter_no=ref_chapter, quote="(이전 회차에 저장된 설정)"
                ),
                type="character",
                explanation=(
                    "이전 회차의 인물 설정과 충돌하는 서술로 보입니다. "
                    "(FakePipeline 예시 결과 — 실제 검출은 LLM 파이프라인이 담당)"
                ),
                confidence=0.87,
            )
        ]

