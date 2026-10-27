r"""배선 검증 — 몸통의 RemotePipeline 으로 이 AI 서버를 실제로 호출해 본다.

DB/Redis/프론트 없이 '몸통 ↔ AI 서버' 계약만 격리해서 확인한다.
몸통의 interface.py / transform.py 를 그대로 import 하므로, 여기를 통과하면
스키마가 어긋나서 분석이 failed 로 떨어질 일은 없다.

실행 (몸통 venv 로 돌려야 한다 — httpx 와 app 패키지가 거기 있다):
    .venv\Scripts\python.exe ai_server\check_contract.py      (저장소 루트에서)
"""
from __future__ import annotations

import asyncio
import os
import sys

# 저장소 구조상 이 파일의 부모(ai_server/)의 부모가 백엔드 루트다.
BACKEND_DIR = os.getenv(
    "GLITCH_BACKEND_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
AI_URL = os.getenv("PIPELINE_REMOTE_URL", "http://127.0.0.1:8100")

sys.path.insert(0, BACKEND_DIR)

from app.pipeline.interface import CanonDelta, CanonSnapshot  # noqa: E402
from app.pipeline.remote import RemotePipeline  # noqa: E402

CHAPTER_1 = "테스트 원문입니다. 헤일트라움에 접속했다."
CHAPTER_2 = "주인공은 소마를 거부했다. 그리고 문을 열었다."

# 인자로 텍스트 파일을 주면 1화 원문으로 쓴다. llm 모드에서 실제 원문으로
# 검증할 때 사용 — echo 모드에서는 응답이 고정이라 의미가 없다.
#     python check_contract.py sample.txt
if len(sys.argv) > 1:
    CHAPTER_1 = open(sys.argv[1], encoding="utf-8").read()


async def main() -> int:
    pipeline = RemotePipeline(AI_URL)

    # ── 1화: 캐논이 비어 있는 상태에서 추출 ──
    empty = CanonSnapshot(project_id="contract-test", up_to_chapter=0)
    out = await pipeline.extract_chapter(CHAPTER_1, empty, title="1화", chapter_no=1)

    delta = out.canon_delta
    print("[extract] OK  ExtractionOutput 검증 통과")
    print(f"  visual_json 보존: {out.visual_json is not None}")
    print(
        "  canon_delta: "
        f"worldview={len(delta.worldview)} characters={len(delta.characters)} "
        f"relations={len(delta.relations)} timeline={len(delta.timeline)} "
        f"spaces={len(delta.spaces)} events={len(delta.events)}"
    )
    if not any(
        (delta.worldview, delta.characters, delta.events, delta.timeline, delta.spaces)
    ):
        print("  !! canon_delta 가 전부 비었다 — 변환이 되지 않았다")
        return 1

    # ── 2화: 1화가 저장됐다고 가정한 캐논으로 검수 ──
    canon = CanonSnapshot(
        project_id="contract-test",
        up_to_chapter=1,
        characters=[
            {"entity_key": c.entity_key, "name": c.name, "source_chapter": 1}
            for c in delta.characters[:3]
        ],
    )
    review = await pipeline.review_chapter(
        CHAPTER_2, canon, CanonDelta(), title="2화", chapter_no=2
    )
    print(f"[review]  OK  ReviewOutput 검증 통과  모순 {len(review.contradictions)}건")
    for c in review.contradictions:
        quote = CHAPTER_2[c.span.start : c.span.end]
        match = "일치" if quote == c.span.quote else f"불일치({quote!r})"
        print(f"  type={c.type} span=({c.span.start},{c.span.end}) 원문대조={match}")

    # ── 1화 검수: scope_ai 는 같은 회차 안의 앞 사건과도 대조하므로 0건이 보장되지 않는다 ──
    first = await pipeline.review_chapter(
        CHAPTER_1, empty, CanonDelta(), title="1화", chapter_no=1
    )
    print(f"[review]  OK  1화(회차 내부 대조) 모순 {len(first.contradictions)}건")

    print("\n전 구간 통과 — 몸통 ↔ AI 서버 배선 정상")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
