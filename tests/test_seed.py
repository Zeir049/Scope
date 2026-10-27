"""시드 데이터 테스트: 멱등성 + '1~3화 저장, 4화 신규' 구조 + 캐논 버전 보존."""
from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import CanonWorldview, Chapter, Project
from app.repository.chapter_repo import ChapterRepository
from app.repository.user_repo import UserRepository
from app.seed import DEMO_EMAIL, seed_demo


async def test_seed_demo_idempotent_and_shape():
    async with SessionLocal() as s:
        # 첫 호출(또는 이미 시드됨) → 둘째 호출은 반드시 멱등(None)
        await seed_demo(s)
        assert await seed_demo(s) is None

        user = await UserRepository(s).get_by_email(DEMO_EMAIL)
        assert user is not None and user.plan == "pro"

        project = (
            await s.execute(select(Project).where(Project.owner_id == user.id))
        ).scalars().first()
        assert project is not None and project.name == "금도끼 은도끼"

        chapters = await ChapterRepository(s).list_by_project(project.id)
        status_by_no = {c.chapter_no: c.status for c in chapters}
        assert len(chapters) == 4
        assert status_by_no[1] == "saved"
        assert status_by_no[2] == "saved"
        assert status_by_no[3] == "saved"
        assert status_by_no[4] == "uploaded"  # 4화 신규

        # 3화에서 currency가 변경됨 → append-only로 2버전 보존, 현재 1개
        currency_rows = (
            await s.execute(
                select(CanonWorldview).where(
                    CanonWorldview.project_id == project.id,
                    CanonWorldview.entity_key == "currency",
                )
            )
        ).scalars().all()
        assert len(currency_rows) == 2
        assert sum(1 for r in currency_rows if r.is_current) == 1
