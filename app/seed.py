"""개발용 시드 데이터 — '금도끼 은도끼' 예시.

명세의 핵심 화면("1~3화 저장됨, 4화 신규")을 그대로 재현한다.
앱 시작 시 SEED_ON_STARTUP=true 면 1회 주입(이미 있으면 멱등 스킵).
프론트를 받기 전에 화면이 채워진 상태를 바로 확인할 수 있게 하는 용도.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Chapter, ChapterStatus, Project
from app.repository.user_repo import UserRepository
from app.service.canon_service import CanonService

logger = logging.getLogger(__name__)

DEMO_EMAIL = "cho@example.com"
DEMO_PASSWORD = "glitch123"
DEMO_NAME = "Cho Euna"

# (chapter_no, 본문, canon_delta) — 1~3화는 저장(canon 병합), 4화는 신규 업로드.
SEED_CHAPTERS: list[tuple[int, str, dict]] = [
    (
        1,
        "정직한 나무꾼이 산속 연못에 도끼를 빠뜨렸다.",
        {
            "worldview": [
                {"entity_key": "currency", "item": "화폐 단위는 '냥'", "detail": "작품 세계의 기본 화폐 단위"},
                {"entity_key": "honesty_rule", "item": "정직한 자가 보상받는다", "detail": "세계관 핵심 규칙"},
            ],
            "characters": [
                {"entity_key": "woodcutter", "name": "나무꾼", "group_name": "주요 인물", "attrs": {"trait": "정직함"}},
                {"entity_key": "mountain_god", "name": "산신령", "group_name": "초월적 존재", "attrs": {"role": "시험자"}},
            ],
            "relations": [
                {"entity_key": "woodcutter-god", "from_char": "woodcutter", "to_char": "mountain_god", "relation": "시험받음"},
            ],
            "timeline": [
                {"entity_key": "scene-pond", "scene_label": "S#1", "order_index": 1, "time_value": "1일차 낮"},
            ],
            "spaces": [
                {"entity_key": "pond", "scene_label": "S#1", "place": "산속 연못", "attrs": {"type": "자연"}},
            ],
            "events": [
                {"entity_key": "drop-axe", "label": "도끼를 연못에 빠뜨림", "stage": "암시", "order_index": 1},
            ],
            "foreshadowing": [
                {"entity_key": "honesty-setup", "label": "정직함 강조", "parent_key": None, "kind": "setup"},
            ],
        },
    ),
    (
        2,
        "산신령이 나타나 금도끼, 은도끼, 쇠도끼를 차례로 들어 보였다.",
        {
            "characters": [
                {"entity_key": "greedy_neighbor", "name": "욕심쟁이 이웃", "group_name": "주요 인물", "attrs": {"trait": "탐욕"}},
            ],
            "relations": [
                {"entity_key": "neighbor-god", "from_char": "greedy_neighbor", "to_char": "mountain_god", "relation": "시험받음"},
            ],
            "timeline": [
                {"entity_key": "scene-god", "scene_label": "S#2", "order_index": 2, "time_value": "1일차 저녁"},
            ],
            "events": [
                {"entity_key": "god-appears", "label": "산신령 등장", "stage": "궁지1", "order_index": 2},
                {"entity_key": "three-axes", "label": "금/은/쇠 도끼 제시", "stage": "궁지2", "order_index": 3},
            ],
        },
    ),
    (
        3,
        "정직하게 쇠도끼라 답한 나무꾼은 세 도끼를 모두 받았고, 욕심쟁이는 빈손으로 돌아갔다.",
        {
            # currency를 같은 entity_key로 변경 → 버전2로 보존(설정 변천사 시연)
            "worldview": [
                {"entity_key": "currency", "item": "화폐 단위는 '냥' (금화 포함)", "detail": "3화에서 금화 언급 추가"},
            ],
            "events": [
                {"entity_key": "reward", "label": "정직한 나무꾼이 금/은/쇠도끼를 모두 받음", "stage": "절정", "order_index": 4},
                {"entity_key": "punish", "label": "욕심쟁이는 빈손", "stage": "절정", "order_index": 5},
            ],
            "foreshadowing": [
                {"entity_key": "honesty-payoff", "label": "정직함으로 보상받음", "parent_key": "honesty-setup", "kind": "payoff"},
            ],
        },
    ),
]

CHAPTER4_TEXT = "4화 원고: 나무꾼은 사실 왼손잡이였다는 새로운 서술이 등장한다."


async def seed_demo(session: AsyncSession) -> str | None:
    """데모 데이터 주입. 이미 있으면 None 반환(멱등)."""
    users = UserRepository(session)
    if await users.get_by_email(DEMO_EMAIL):
        logger.info("seed skip: demo user already exists")
        return None

    user = await users.create(DEMO_EMAIL, hash_password(DEMO_PASSWORD), DEMO_NAME)
    user.plan = "pro"

    project = Project(
        owner_id=user.id,
        name="금도끼 은도끼",
        author="Cho",
        description="정직한 나무꾼이 산신령의 시험을 통과하는 이야기",
    )
    session.add(project)
    await session.flush()

    canon = CanonService(session)
    for chapter_no, text, delta in SEED_CHAPTERS:
        chapter = Chapter(
            project_id=project.id,
            chapter_no=chapter_no,
            title=f"{chapter_no}화",
            raw_text=text,
            status=ChapterStatus.saved.value,  # 1~3화 저장됨
        )
        session.add(chapter)
        await canon.merge_delta(project.id, delta, source_chapter=chapter_no)

    # 4화 신규 (업로드만, 분석 전)
    session.add(
        Chapter(
            project_id=project.id,
            chapter_no=4,
            title="4화",
            raw_text=CHAPTER4_TEXT,
            status=ChapterStatus.uploaded.value,
        )
    )
    await session.commit()
    logger.info("seed done: user=%s project=%s (1~3화 saved, 4화 new)", DEMO_EMAIL, project.id)
    return str(project.id)


async def run_seed() -> None:
    async with SessionLocal() as session:
        await seed_demo(session)
