"""몸통 계약(/extract, /review) ↔ scope_ai 파이프라인 어댑터.

scope_ai/ 는 AI 파트 저장소(weave, AI 브랜치 Project_scope_AI_refactored)의 사본이다.
업스트림과 다시 맞추기 쉽도록 그쪽은 고치지 않고, 몸통 계약에 맞추는 일은 전부 여기서 한다.

    /extract  → analyze_submission → process_ep(ID 통합·ep_global 누적)
                → 이번 회차 ep 를 global ID 로 바꿔 rich JSON 으로 반환
    /review   → (추출 상태 없으면 보충) → 누락 사건 임베딩 → ERS Top-K
                → review_submission → issues 를 ContradictionOut 으로 변환

상태: scope_ai 는 작품별 누적 상태(ep_global, 임베딩, ERS)를 파일로 쌓는다.
SCOPE_DATA_ROOT/{project_id}/ 아래에 두며, 회차 번호(chapter_no)가 submission 번호다.
몸통 DB 가 캐논의 진실 원천이고, 여기 파일은 ID 통합·관련 사건 검색용 보조 색인이다.
  - 같은 회차를 다시 추출하면 그 회차가 남긴 항목을 먼저 걷어내고 다시 쌓는다(멱등).
  - 몸통에서 사용자가 수정한 delta 는 반영되지 않는다 — ERS/검수는 LLM 추출본 기준.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import re
import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable

from fastapi import HTTPException

from scope_ai.analysis import analyze_submission
from scope_ai.common import EP_FIELDS, StoryPaths, load_json, save_json
from scope_ai.embedding import embed_events
from scope_ai.embedding.base import BaseEmbedder
from scope_ai.embedding.event_embedder import EMBEDDING_FIELDS
from scope_ai.ers import rank_related_events
from scope_ai.id_split import process_ep
from scope_ai.id_split.reference_mapper import replace_references
from scope_ai.review import review_submission

from server.schemas import (
    CanonSnapshot,
    ConflictRef,
    ContradictionOut,
    ExtractRequest,
    ReviewRequest,
    ReviewResponse,
)
from server.spans import span_of

logger = logging.getLogger("glitch-ai.scope")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("SCOPE_DATA_ROOT") or BASE_DIR / "Data" / "stories")
EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "bge").lower()
ERS_TOP_K = int(os.getenv("ERS_TOP_K", "5"))

RULE_DOC_PREFIX = (
    "[아래 본문은 서사가 아니라 작가가 직접 작성한 설정/규칙 문서다. "
    "각 항목을 명시적 세계관 규칙(worldview_rules)으로 정리하라.]\n\n"
)

# scope_ai 검수 type → 몸통 ContradictionOut.type
_TYPE_MAP = {
    "setting": "setting",
    "character": "character",
    "time": "timeline",
    "location": "space",
    "causal": "event",
    "other": "event",
}
# scope_ai 는 확신도 대신 severity 두 단계만 준다.
_SEVERITY_CONFIDENCE = {"conflict": 0.9, "check_needed": 0.6}

# time_info x축(직전 사건과의 간격) → 사람이 읽는 표현. 몸통 transform 은
# times[].expression 을 timeline.time_value 로 쓰므로 비어 있으면 타임라인이 통째로 빠진다.
_TIME_GAPS = {
    1: "수초~수분",
    2: "수십 분~수 시간",
    3: "같은 날 다른 시간대",
    4: "약 하루",
    5: "수일",
    6: "수주~수개월",
    7: "수년",
    8: "아주 먼 시점",
}
_TIMELINE_LABELS = {"flashback": "회상", "flashforward": "미래 장면", "parallel": "병행"}


# ── 공통 ───────────────────────────────────────────────
def story_id_of(canon: CanonSnapshot) -> str:
    """project_id 를 폴더명으로 안전하게 쓴다."""
    return re.sub(r"[^0-9A-Za-z_-]", "_", canon.project_id) or "default"


def chapter_no_of(req: ExtractRequest) -> int:
    if req.chapter_no and req.chapter_no >= 1:
        return req.chapter_no
    guessed = req.canon.up_to_chapter + 1
    logger.warning(
        "chapter_no 가 없어 up_to_chapter+1=%d 로 추정 — 몸통을 최신 계약으로 올릴 것", guessed
    )
    return guessed


def _paths(story_id: str) -> StoryPaths:
    return StoryPaths(story_id, DATA_ROOT)


_story_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _llm_caller(title: str | None) -> Callable[[str, str], str]:
    from server.llm import call_sync

    # 계약(interface.py): title 이 "[규칙]" 으로 시작하면 서사가 아니라 설정 문서다.
    # 저장되는 submission 원문은 그대로 두고 LLM 에 보내는 본문에만 안내를 붙인다.
    prefix = RULE_DOC_PREFIX if (title or "").startswith("[규칙]") else ""
    return lambda text, system: call_sync(prefix + text, system)


# ── 임베더 ──────────────────────────────────────────────
class HashEmbedder(BaseEmbedder):
    """torch 없이 도는 결정적 임베더(글자 2-gram 해싱). 개발·테스트용 — 의미 유사도는 없다."""

    model_name = "hash-2gram-256"
    dim = 256

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        compact = re.sub(r"\s+", "", text)
        grams = [compact[i : i + 2] for i in range(max(len(compact) - 1, 1))]
        for gram in grams:
            digest = hashlib.md5(gram.encode("utf-8")).digest()
            vec[int.from_bytes(digest[:4], "little") % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


_embedder: BaseEmbedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> BaseEmbedder:
    """프로세스당 1회만 로드한다 (BGE-M3 는 ~2GB 라 요청마다 만들면 안 된다)."""
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            if EMBEDDING_MODE == "hash":
                _embedder = HashEmbedder()
            elif EMBEDDING_MODE == "bge":
                from scope_ai.embedding.bge_m3 import BGEM3Embedder

                logger.info("BGE-M3 로드 시작 (첫 실행이면 모델 다운로드 포함)")
                _embedder = BGEM3Embedder(device=os.getenv("EMBEDDING_DEVICE") or None)
                logger.info("BGE-M3 로드 완료")
            else:
                raise HTTPException(500, f"알 수 없는 EMBEDDING_MODE: {EMBEDDING_MODE}")
        return _embedder


# ── 상태 관리 ───────────────────────────────────────────
def _forget_submission(paths: StoryPaths, n: int) -> bool:
    """회차 n 이 ep_global·임베딩에 남긴 흔적을 걷어낸다. 재추출을 멱등으로 만든다."""
    if not paths.ep_global.exists():
        return False
    global_ep = load_json(paths.ep_global)
    changed = False
    removed_events = {
        e.get("event_id") for e in global_ep["events"] if e.get("source_submission") == n
    }
    for field in ("worldview_rules", "events", "times", "locations"):
        kept = [x for x in global_ep[field] if x.get("source_submission") != n]
        changed |= len(kept) != len(global_ep[field])
        global_ep[field] = kept

    characters = []
    for character in global_ep["characters"]:
        sources = character.get("source_submissions") or []
        if n in sources:
            changed = True
            sources = [s for s in sources if s != n]
            if not sources:
                continue  # 이 회차에서 처음 나온 인물
            character["source_submissions"] = sources
        characters.append(character)
    global_ep["characters"] = characters

    if changed:
        save_json(global_ep, paths.ep_global)
    if removed_events and paths.event_embeddings.exists():
        store = load_json(paths.event_embeddings)
        store["events"] = [
            e for e in store.get("events", []) if e.get("event_id") not in removed_events
        ]
        save_json(store, paths.event_embeddings)
    return changed


def _is_merged(paths: StoryPaths, n: int) -> bool:
    """회차 n 의 ep 가 ep_global 에 반영돼 있는가."""
    if not paths.ep_global.exists():
        return False
    ep = load_json(paths.ep(n))
    if not any(ep.get(field) for field in EP_FIELDS):
        return True  # 반영할 것이 없는 회차
    global_ep = load_json(paths.ep_global)
    if any(
        x.get("source_submission") == n
        for field in ("worldview_rules", "events", "times", "locations")
        for x in global_ep[field]
    ):
        return True
    return any(n in (c.get("source_submissions") or []) for c in global_ep["characters"])


def _ensure_embeddings(paths: StoryPaths) -> list[str]:
    """ep_global 사건 중 임베딩이 없는 것을 채운다.

    scope_ai 의 embed_submission_events 는 이번 회차만 임베딩하므로, 검수 없이
    추출만 하고 지나간 회차나 임베더를 바꾼 경우 이전 사건이 빠진다. 여기서 보충한다.
    """
    embedder = get_embedder()
    model_name = getattr(embedder, "model_name", embedder.__class__.__name__)
    global_ep = load_json(paths.ep_global)

    store = load_json(paths.event_embeddings) if paths.event_embeddings.exists() else None
    if store is None or store.get("model") != model_name:
        if store is not None:
            logger.info("임베딩 모델 변경(%s → %s) — 전체 재임베딩", store.get("model"), model_name)
        store = {"model": model_name, "embedding_fields": list(EMBEDDING_FIELDS), "events": []}

    have = {e.get("event_id") for e in store["events"]}
    missing = [e for e in global_ep["events"] if e.get("event_id") not in have]
    if missing:
        store["events"].extend(embed_events(missing, embedder))
    save_json(store, paths.event_embeddings)
    return [e.get("event_id") for e in missing]


# ── 변환 ───────────────────────────────────────────────
def describe_time(time: dict) -> str:
    info = time.get("time_info")
    try:
        gap = int(info[0]) if isinstance(info, list) and info and info[0] is not None else None
    except (TypeError, ValueError):
        gap = None

    if gap == 0:
        text = "직전 사건과 같은 시점"
    elif gap in _TIME_GAPS:
        direction = "전" if time.get("offset") == 0 else "후"
        text = f"직전 사건보다 {_TIME_GAPS[gap]} {direction}"
    else:
        text = "시점 불명"

    label = _TIMELINE_LABELS.get(time.get("timeline_type") or "")
    return f"[{label}] {text}" if label else text


def to_visual(ep: dict, id_maps: dict[str, dict[str, str]]) -> dict:
    """이번 회차 ep(local ID) → global ID 로 바꾼 rich JSON.

    몸통은 rule_id/character_id/... 를 entity_key 로 쓰므로, 회차 접두사가 붙은
    local ID(3_CHAR_001)를 그대로 주면 같은 인물이 회차마다 다른 캐논 항목이 된다.
    """
    visual = {
        field: replace_references(ep.get(field, []), list(id_maps.values()))
        for field in EP_FIELDS
    }
    for time in visual["times"]:
        if not time.get("expression"):
            time["expression"] = describe_time(time)
    return visual


def to_contradictions(review: dict, global_ep: dict, chapter_text: str) -> list[ContradictionOut]:
    if review.get("parse_error"):
        logger.error("review: JSON 파싱 실패. 응답 앞부분: %r", str(review.get("raw_text"))[:300])
        raise HTTPException(502, "review: 모델이 유효한 JSON 을 주지 않았습니다.")

    events = {e["event_id"]: e for e in global_ep["events"] if e.get("event_id")}
    out: list[ContradictionOut] = []
    for item in review.get("events") or []:
        source = events.get(item.get("source_event_id")) or {}
        # 검수 프롬프트는 원문 인용을 주지 않으므로 신규 사건의 근거 문장으로 위치를 잡는다.
        span = span_of(chapter_text, (source.get("source_text") or "").strip())
        for issue in item.get("issues") or []:
            related = events.get(issue.get("related_event_id")) or {}
            explanation = (issue.get("description") or "").strip()
            evidence = [e.strip() for e in issue.get("evidence") or [] if isinstance(e, str) and e.strip()]
            if evidence:
                explanation += "\n근거: " + " / ".join(evidence)
            out.append(
                ContradictionOut(
                    span=span,
                    conflict_ref=ConflictRef(
                        chapter_no=related.get("source_submission"),
                        quote=related.get("source_text") or related.get("summary"),
                    ),
                    type=_TYPE_MAP.get(issue.get("type") or "", "event"),
                    explanation=explanation,
                    confidence=_SEVERITY_CONFIDENCE.get(issue.get("severity") or "", 0.6),
                )
            )
    return out


# ── 단계 (동기 — 워커 스레드에서 돈다) ──────────────────────
def _extract_sync(story_id: str, n: int, text: str, title: str | None) -> dict:
    paths = _paths(story_id)
    if _forget_submission(paths, n):
        logger.info("[extract] story=%s ch=%d 재추출 — 이전 결과를 걷어냄", story_id, n)
    try:
        ep = analyze_submission(story_id, n, text, data_root=DATA_ROOT, llm_callable=_llm_caller(title))
    except ValueError as e:
        raise HTTPException(502, f"extract: {e}") from e
    split = process_ep(story_id, n, ep=ep, data_root=DATA_ROOT)
    logger.info("[extract] story=%s ch=%d counts=%s", story_id, n, split["counts"])
    return to_visual(ep, split["id_maps"])


def _ensure_extracted(story_id: str, n: int, text: str, title: str | None) -> None:
    """검수 전에 회차 n 의 추출 상태가 원문과 맞게 있는지 확인하고, 없으면 채운다."""
    paths = _paths(story_id)
    saved_text = paths.submission(n).read_text(encoding="utf-8") if paths.submission(n).exists() else None
    if not paths.ep(n).exists() or saved_text != text:
        # 서버 데이터를 지웠거나, echo 로 추출했거나, 추출 뒤 원문이 바뀐 경우. LLM 1회 추가.
        logger.warning("[review] story=%s ch=%d 추출 상태가 없거나 원문이 달라 지금 추출함", story_id, n)
        _extract_sync(story_id, n, text, title)
    elif not _is_merged(paths, n):
        logger.warning("[review] story=%s ch=%d ep 는 있으나 ep_global 미반영 — 다시 병합", story_id, n)
        process_ep(story_id, n, data_root=DATA_ROOT)


def _embed_sync(story_id: str, n: int, text: str, title: str | None) -> None:
    _ensure_extracted(story_id, n, text, title)
    embedded = _ensure_embeddings(_paths(story_id))
    logger.info("[review] story=%s ch=%d 임베딩 %d건", story_id, n, len(embedded))


def _detect_sync(story_id: str, n: int, text: str, title: str | None) -> list[ContradictionOut]:
    paths = _paths(story_id)
    ers = rank_related_events(story_id, n, top_k=ERS_TOP_K, data_root=DATA_ROOT)
    if not ers["events"]:
        logger.info("[review] story=%s ch=%d 신규 사건 없음 — LLM 호출 생략", story_id, n)
        return []
    review = review_submission(story_id, n, data_root=DATA_ROOT, llm_callable=_llm_caller(title))
    contradictions = to_contradictions(review, load_json(paths.ep_global), text)
    logger.info("[review] story=%s ch=%d 모순 %d건", story_id, n, len(contradictions))
    return contradictions


# ── 엔드포인트용 진입점 ───────────────────────────────────
async def extract(req: ExtractRequest) -> dict:
    story_id, n = story_id_of(req.canon), chapter_no_of(req)
    async with _story_locks[story_id]:
        return await asyncio.to_thread(_extract_sync, story_id, n, req.chapter_text, req.title)


async def review(req: ReviewRequest) -> ReviewResponse:
    story_id, n = story_id_of(req.canon), chapter_no_of(req)
    async with _story_locks[story_id]:
        # 두 단계로 나눠 둔 것은 NDJSON 스트림(embedding_done → result) 계약에 그대로 맞추기 위해서다.
        await asyncio.to_thread(_embed_sync, story_id, n, req.chapter_text, req.title)
        contradictions = await asyncio.to_thread(_detect_sync, story_id, n, req.chapter_text, req.title)
    return ReviewResponse(contradictions=contradictions)
