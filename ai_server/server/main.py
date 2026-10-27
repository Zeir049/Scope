"""Glitch LLM 파이프라인 서버.

몸통(저장소 루트 app/)의 RemotePipeline 이 HTTP 로 부르는 쪽. 계약은
app/pipeline/interface.py 하나뿐이고, 그 안쪽(프롬프트/모델/검색)은 이 서버의 자유다.

모드 (엔드포인트별로 따로 켠다):
  EXTRACT_MODE=echo  sample_visual.json 을 그대로 반환. LLM 호출 없음.
  EXTRACT_MODE=llm   scope_ai 로 1차 추출 (Claude 구조화 → ID 통합).
  REVIEW_MODE=echo   원문 앞부분을 물고 있는 가짜 모순 1건 반환.
  REVIEW_MODE=llm    scope_ai 로 2차 검수 (임베딩 → ERS Top-K → Claude 검토).

llm 모드의 실제 로직은 scope_ai/ (AI 파트 원본 사본)에 있고, 몸통 계약에 맞추는
변환은 server/scope_bridge.py 가 한다.

echo 는 임시 구현이 아니라 상시 유지하는 스위치다:
  - 분석이 깨졌을 때 echo 로 돌려보면 원인이 배선인지 LLM인지 1분에 갈린다
  - API 키 없는 팀원도 프론트/몸통 전 구간을 돌릴 수 있다
  - 응답이 결정적이라 자동 테스트를 붙일 수 있다
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from server.schemas import (
    ConflictRef,
    ContradictionOut,
    ExtractRequest,
    ReviewRequest,
    ReviewResponse,
)
from server.spans import span_of

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
EXTRACT_MODE = os.getenv("EXTRACT_MODE", "echo").lower()
REVIEW_MODE = os.getenv("REVIEW_MODE", "echo").lower()

# 실제 LLM 이 내려줄 rich JSON 샘플(prompt_result_1 포맷, '헤일트라움').
# 몸통의 app/pipeline/fake_visual.json 과 같은 파일 — 프론트 하드코딩
# 데모(DEMO_WORLDVIEW_ROUND1)와도 같은 구조다. 모듈 로드 시 1회만 읽는다.
SAMPLE_VISUAL: dict = json.loads(
    (BASE_DIR / "sample_visual.json").read_text(encoding="utf-8")
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("glitch-ai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 검수가 llm 이면 임베더(BGE-M3 ~2GB)를 기동 직후 백그라운드로 미리 올린다.
    # 첫 검수 요청이 모델 로드까지 떠안으면 몸통 타임아웃(300초)에 걸릴 수 있다.
    if REVIEW_MODE == "llm":
        from server.scope_bridge import get_embedder

        def _report(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("임베더 사전 로드 실패: %s", task.exception())

        asyncio.create_task(asyncio.to_thread(get_embedder)).add_done_callback(_report)
    yield


app = FastAPI(
    title="glitch-ai",
    description="Glitch 백엔드가 호출하는 LLM 분석 파이프라인 서버",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    info = {
        "ok": True,
        "extract_mode": EXTRACT_MODE,
        "review_mode": REVIEW_MODE,
        "sample_keys": sorted(SAMPLE_VISUAL.keys()),
    }
    if "llm" in (EXTRACT_MODE, REVIEW_MODE):
        from server import scope_bridge

        info["scope"] = {
            "data_root": str(scope_bridge.DATA_ROOT),
            "embedding_mode": scope_bridge.EMBEDDING_MODE,
            "embedder_loaded": scope_bridge._embedder is not None,
            "ers_top_k": scope_bridge.ERS_TOP_K,
        }
    return info


@app.get("/health/llm")
async def health_llm() -> dict:
    """Claude 통로가 뚫려 있는지만 확인한다 (max_tokens=1).

    /health 는 서버만 본다. 이쪽은 실제로 Anthropic 까지 왕복하되
    출력 1토큰이라 비용이 거의 들지 않는다. 분석 테스트 대용이 아니다.
    """
    from server.llm import ping

    return await ping()


@app.post("/extract")
async def extract(req: ExtractRequest) -> dict:
    """1차 추출. 6기준 구조화 데이터를 뽑는다. 모순 판정은 하지 않는다.

    응답은 prompt_result_1 rich JSON 을 그대로 돌려준다. 몸통의
    looks_like_visual_json() 이 잡아서 CanonDelta 로 변환하고, 원본은
    analysis_results.raw_output 에 보존돼 GET /visual 로 프론트에 내려간다.
    """
    logger.info(
        "[extract] mode=%s ch=%s title=%r text_len=%d canon_items=%d",
        EXTRACT_MODE,
        req.chapter_no,
        req.title,
        len(req.chapter_text),
        req.canon.total_items(),
    )

    if EXTRACT_MODE == "echo":
        return SAMPLE_VISUAL

    if EXTRACT_MODE == "llm":
        from server.scope_bridge import extract as scope_extract

        return await scope_extract(req)

    raise HTTPException(500, f"알 수 없는 EXTRACT_MODE: {EXTRACT_MODE}")


@app.post("/review", response_model=ReviewResponse)
async def review(req: ReviewRequest) -> ReviewResponse:
    """2차 검수. 기존 캐논 + 확정된 델타를 대조해 모순 목록을 반환한다.

    /extract 와 달리 응답 스키마가 고정이다 — 몸통이 ReviewOutput 으로
    바로 검증하므로 필드 하나만 어긋나도 분석이 failed 로 떨어진다.
    """
    logger.info(
        "[review] mode=%s ch=%s title=%r text_len=%d canon_items=%d delta_keys=%s",
        REVIEW_MODE,
        req.chapter_no,
        req.title,
        len(req.chapter_text),
        req.canon.total_items(),
        sorted(req.delta.keys()),
    )

    if REVIEW_MODE == "echo":
        return _echo_review(req)

    if REVIEW_MODE == "llm":
        from server.scope_bridge import review as scope_review

        return await scope_review(req)

    raise HTTPException(500, f"알 수 없는 REVIEW_MODE: {REVIEW_MODE}")


def _echo_review(req: ReviewRequest) -> ReviewResponse:
    """배선 확인용 가짜 모순.

    원문 앞부분을 실제로 물고 있으므로 프론트 하이라이트까지 눈으로 확인된다.
    기존 캐논이 비어 있으면(1화) 대조할 대상이 없으므로 빈 목록을 준다 —
    실제 파이프라인의 동작과 같게 맞춘 것.
    """
    if req.canon.total_items() == 0:
        return ReviewResponse(contradictions=[])

    quote = req.chapter_text[:24].strip()
    return ReviewResponse(
        contradictions=[
            ContradictionOut(
                span=span_of(req.chapter_text, quote),
                conflict_ref=ConflictRef(
                    chapter_no=req.canon.up_to_chapter or None,
                    quote="(이전 회차에 저장된 설정)",
                ),
                type="character",
                explanation=(
                    "에코 모드 응답입니다 — 배선 확인용 더미 모순이며 "
                    "실제 검출 결과가 아닙니다. REVIEW_MODE=llm 으로 교체하세요."
                ),
                confidence=0.5,
            )
        ]
    )
