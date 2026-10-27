"""구현 A — 외부 LLM 파이프라인 서버에 httpx로 붙이는 어댑터 (스켈레톤).

진짜 파이프라인 서버가 준비되면 여기를 채운다. 입출력은 interface.py의
CanonSnapshot / AnalysisOutput JSON 스키마를 그대로 주고받는다.
"""
from __future__ import annotations

import logging

import httpx

from app.pipeline.interface import (
    CanonDelta,
    CanonSnapshot,
    ExtractionOutput,
    PipelineHealth,
    ReviewOutput,
)
from app.pipeline.transform import looks_like_visual_json, visual_to_canon_delta

logger = logging.getLogger(__name__)

# 사전 점검은 "켜져 있나"만 본다 — 분석 타임아웃(300초)과 달리 짧게 끊는다.
HEALTH_TIMEOUT_SECONDS = 5


class RemotePipeline:
    def __init__(self, base_url: str) -> None:
        if not base_url:
            raise ValueError("PIPELINE_REMOTE_URL 이 설정되지 않았습니다.")
        self.base_url = base_url.rstrip("/")

    async def health(self) -> PipelineHealth:
        url = f"{self.base_url}/health"
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
                resp = await client.get(url)
        except httpx.ConnectError:
            logger.warning("pipeline health: connect failed url=%s", url)
            return self._down("AI 서버에 연결할 수 없습니다. AI 서버가 켜져 있는지 확인하세요.")
        except httpx.TimeoutException:
            logger.warning("pipeline health: timeout url=%s", url)
            return self._down(
                f"AI 서버가 응답하지 않습니다 ({HEALTH_TIMEOUT_SECONDS}초 초과). 서버 상태를 확인하세요."
            )
        except httpx.HTTPError as e:
            logger.warning("pipeline health: %s url=%s", e.__class__.__name__, url)
            return self._down(f"AI 서버 연결 중 오류가 발생했습니다 ({e.__class__.__name__}).")

        if resp.status_code != 200:
            logger.warning("pipeline health: HTTP %s url=%s", resp.status_code, url)
            return self._down(f"AI 서버가 비정상 응답을 보냈습니다 (HTTP {resp.status_code}).")
        try:
            info = resp.json()
        except ValueError:
            return self._down("AI 서버 응답을 해석할 수 없습니다 (JSON 아님).")
        if not isinstance(info, dict) or info.get("ok") is False:
            return self._down("AI 서버가 준비되지 않았다고 응답했습니다.", info if isinstance(info, dict) else {})

        # 검수 llm 모드에서 임베딩 모델이 아직 올라오는 중이면 첫 검수가 느릴 수 있다 — 막지는 않고 알린다.
        scope = info.get("scope") or {}
        message = "AI 서버 연결됨"
        if info.get("review_mode") == "llm" and scope.get("embedder_loaded") is False:
            message += " (임베딩 모델 준비 중 — 첫 검토가 느릴 수 있음)"
        return PipelineHealth(ok=True, mode="remote", message=message, info=info)

    @staticmethod
    def _down(message: str, info: dict | None = None) -> PipelineHealth:
        return PipelineHealth(ok=False, mode="remote", message=message, info=info or {})

    async def extract_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ExtractionOutput:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.base_url}/extract",
                json={
                    "chapter_text": chapter_text,
                    "canon": canon.model_dump(),
                    "title": title,
                    "chapter_no": chapter_no,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            # 파이프라인 서버가 rich JSON(prompt_result_1 포맷)을 주면 변환해서
            # 받아들이고 원본은 visual_json으로 보존한다. ExtractionOutput
            # 포맷을 주면 그대로 검증한다 — 두 계약 모두 지원.
            if looks_like_visual_json(payload):
                return ExtractionOutput(
                    highlighted_text=chapter_text,
                    canon_delta=visual_to_canon_delta(payload),
                    visual_json=payload,
                )
            return ExtractionOutput.model_validate(payload)

    async def review_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,
        delta: CanonDelta,
        title: str | None = None,
        *,
        chapter_no: int | None = None,
    ) -> ReviewOutput:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.base_url}/review",
                json={
                    "chapter_text": chapter_text,
                    "canon": canon.model_dump(),
                    "delta": delta.model_dump(),
                    "title": title,
                    "chapter_no": chapter_no,
                },
            )
            resp.raise_for_status()
            return ReviewOutput.model_validate(resp.json())
