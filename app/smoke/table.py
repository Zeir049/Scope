# ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 삭제. 삭제법은 app/smoke/README.md 참조
"""smoke_checks 테이블 자체 생성 (Alembic 마이그레이션 체인 밖).

앱 시작 시 이 테이블만 idempotent 하게 만든다. 다른 테이블/마이그레이션은 건드리지 않음.
"""
from __future__ import annotations

from app.core.db import engine
from app.smoke.model import SmokeCheck


async def ensure_smoke_table() -> None:
    """smoke_checks 테이블이 없으면 생성(있으면 무시). 매 기동마다 안전하게 호출 가능."""
    async with engine.begin() as conn:
        # 이 테이블 하나만 생성 (create_all 로 전체를 건드리지 않는다). checkfirst=True 로 멱등.
        await conn.run_sync(
            lambda sync_conn: SmokeCheck.__table__.create(sync_conn, checkfirst=True)
        )
