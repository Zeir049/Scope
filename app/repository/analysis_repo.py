"""분석 결과 + 모순 DB 접근."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalysisResult, Contradiction
from app.pipeline.interface import ContradictionOut


class AnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_latest(self, chapter_id: uuid.UUID) -> AnalysisResult | None:
        res = await self.s.execute(
            select(AnalysisResult)
            .where(AnalysisResult.chapter_id == chapter_id)
            .order_by(AnalysisResult.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def clear_for_chapter(self, chapter_id: uuid.UUID) -> None:
        """재분석 시 이전 결과/모순 제거."""
        await self.delete_contradictions(chapter_id)
        await self.s.execute(
            delete(AnalysisResult).where(AnalysisResult.chapter_id == chapter_id)
        )

    async def delete_contradictions(self, chapter_id: uuid.UUID) -> None:
        """모순만 제거(추출 결과 analysis_results는 보존).

        reviewed 상태에서 델타를 편집하면 기존 모순이 낡은 결과가 되므로 이걸로 지운다.
        """
        await self.s.execute(
            delete(Contradiction).where(Contradiction.chapter_id == chapter_id)
        )

    async def create_pending(self, chapter_id: uuid.UUID) -> AnalysisResult:
        row = AnalysisResult(chapter_id=chapter_id, progress=0)
        self.s.add(row)
        await self.s.flush()
        return row

    async def save_extraction(
        self,
        row: AnalysisResult,
        highlighted_text: str,
        canon_delta: dict,
        visual_json: dict | None = None,
    ) -> None:
        """1차 추출 결과 저장(canon_delta는 save 시 병합에 재사용).

        visual_json = LLM이 준 원본 rich JSON(시각화용) — 전용 컬럼에 보존.
        성공했으므로 재시도 이전의 실패 기록(raw_output)은 비운다.
        """
        row.highlighted = {"highlighted_text": highlighted_text}
        row.canon_delta = canon_delta
        row.visual_json = visual_json
        row.raw_output = None
        row.progress = 100

    async def update_canon_delta(
        self, row: AnalysisResult, canon_delta: dict
    ) -> None:
        """편집된 canon_delta를 통째로 재할당한다.

        ⚠️ JSONB는 in-place 변경(list.append 등)을 SQLAlchemy가 dirty로 못 잡으므로,
        반드시 새 dict를 통째 재할당해야 UPDATE가 발생한다.
        """
        row.canon_delta = canon_delta
        await self.s.flush()

    @staticmethod
    async def save_failure(
        row: AnalysisResult, detail: str, stage: str | None = None
    ) -> None:
        """실패 사유 + 실패 단계(extract|review)를 raw_output에 기록."""
        payload = {"error": detail}
        if stage:
            payload["stage"] = stage
        row.raw_output = payload

    async def add_contradictions(
        self, chapter_id: uuid.UUID, items: list[ContradictionOut]
    ) -> None:
        for c in items:
            self.s.add(
                Contradiction(
                    chapter_id=chapter_id,
                    span=c.span.model_dump(),
                    conflict_ref=c.conflict_ref.model_dump(),
                    type=c.type,
                    explanation=c.explanation,
                    confidence=c.confidence,
                )
            )

    async def list_contradictions(
        self, chapter_id: uuid.UUID
    ) -> list[Contradiction]:
        res = await self.s.execute(
            select(Contradiction).where(Contradiction.chapter_id == chapter_id)
        )
        return list(res.scalars().all())

    async def count_contradictions(self, chapter_id: uuid.UUID) -> int:
        n = await self.s.scalar(
            select(func.count())
            .select_from(Contradiction)
            .where(Contradiction.chapter_id == chapter_id)
        )
        return int(n or 0)

    async def get_contradiction(
        self, chapter_id: uuid.UUID, contradiction_id: uuid.UUID
    ) -> Contradiction | None:
        """그 회차에 속한 모순만 (다른 회차의 id 로는 못 찾는다)."""
        res = await self.s.execute(
            select(Contradiction).where(
                Contradiction.id == contradiction_id,
                Contradiction.chapter_id == chapter_id,
            )
        )
        return res.scalar_one_or_none()
