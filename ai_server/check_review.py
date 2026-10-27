r"""2차 검수 시나리오 테스트 — 심어둔 모순은 잡고, 함정은 안 잡는지 본다.

배선만 보는 check_contract.py 와 달리 여기는 **판정 품질**을 본다.
1화로 캐논을 만든 뒤, 진짜 모순 2건과 모순이 아닌 함정 2건을 섞은 2화를 넣는다.

실행 (몸통 venv):
    .venv\Scripts\python.exe ai_server\check_review.py        (저장소 루트에서)
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

CHAPTER_1 = open(
    os.path.join(os.path.dirname(__file__), "sample_chapter.txt"), encoding="utf-8"
).read()

# 2화: 진짜 모순 2건 + 함정 2건
CHAPTER_2 = (
    "s#3. 아르카 중앙구, 3년 뒤\n"
    "연우는 스물세 번째 생일 아침에도 아무렇지 않게 지상을 걸어 돌아왔다.\n"  # 모순 1: 규칙 위반
    "집에 들어서자 어머니 서린이 부엌에서 아침을 차리고 있었다.\n"  # 모순 2: 죽은 인물 등장
    "겁이 많던 하람은 이제 형보다 먼저 강하복을 입는 아이가 되어 있었다.\n"  # 함정 1: 인물의 성장
    "아르카는 일곱 개의 구역으로 나뉘어 있고, 중앙구에는 관리국이 있다.\n"  # 함정 2: 새 정보 추가
)

TRAPS = ("하람", "일곱 개", "구역", "관리국")


async def main() -> int:
    pipeline = RemotePipeline(AI_URL)

    # ── 1화 추출 → 캐논 구성 ──
    out = await pipeline.extract_chapter(
        CHAPTER_1, CanonSnapshot(project_id="review-test"), title="1화"
    )
    d = out.canon_delta
    canon = CanonSnapshot(
        project_id="review-test",
        up_to_chapter=1,
        worldview=[
            {"entity_key": w.entity_key, "item": w.item, "detail": w.detail,
             "source_chapter": 1} for w in d.worldview
        ],
        characters=[
            {"entity_key": c.entity_key, "name": c.name, "attrs": c.attrs,
             "source_chapter": 1} for c in d.characters
        ],
        relations=[
            {"entity_key": r.entity_key, "from_char": r.from_char,
             "to_char": r.to_char, "relation": r.relation, "source_chapter": 1}
            for r in d.relations
        ],
        events=[
            {"entity_key": e.entity_key, "label": e.label, "source_chapter": 1}
            for e in d.events
        ],
    )
    print(f"1화 캐논 구성: 규칙 {len(canon.worldview)} 인물 {len(canon.characters)} "
          f"관계 {len(canon.relations)} 사건 {len(canon.events)}")

    # ── 2화 검수 ──
    review = await pipeline.review_chapter(CHAPTER_2, canon, CanonDelta(), title="2화")
    print(f"\n검출 {len(review.contradictions)}건\n")

    ok = True
    for c in review.contradictions:
        cut = CHAPTER_2[c.span.start : c.span.end]
        verbatim = cut == c.span.quote and c.span.end > c.span.start
        trap = next((t for t in TRAPS if t in c.span.quote), None)
        mark = "함정오탐" if trap else "정상"
        if trap:
            ok = False
        if not verbatim:
            ok = False
            mark += " / 인용불일치"
        print(f"  [{mark}] type={c.type} conf={c.confidence} ch={c.conflict_ref.chapter_no}")
        print(f"    quote: {c.span.quote[:50]}")
        print(f"    이유 : {c.explanation[:80]}")

    if not review.contradictions:
        print("  !! 심어둔 모순 2건을 하나도 못 잡았다")
        ok = False

    # ── 음성 대조: 캐논이 비면 무조건 0건 ──
    empty = await pipeline.review_chapter(
        CHAPTER_2, CanonSnapshot(project_id="review-test"), CanonDelta(), title="1화"
    )
    print(f"\n캐논 빈 상태 검수: {len(empty.contradictions)}건", end=" ")
    if empty.contradictions:
        print("!! 1화에서 오탐 발생")
        ok = False
    else:
        print("(정상)")

    print("\n" + ("통과" if ok else "확인 필요"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
