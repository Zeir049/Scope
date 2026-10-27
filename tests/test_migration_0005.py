"""마이그레이션 0005 왕복: 세계관·관계·시간·사건 테이블의 attrs 컬럼.

downgrade 0004 에서 네 테이블 모두 attrs 가 없고, upgrade head 에서 다시 생기는지 본다.
(모델 ↔ 마이그레이션 일치는 test_migration_0004.test_models_match_migrations 가 본다.)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import settings

TABLES = ("canon_worldview", "canon_relations", "canon_timeline", "canon_events")


def _columns(conn, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_0005_downgrade_upgrade_attrs_columns():
    cfg = Config("alembic.ini")
    engine = sa.create_engine(settings.database_url_sync)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0004_fusion_chapters")
    try:
        with engine.connect() as conn:
            for t in TABLES:
                assert "attrs" not in _columns(conn, t), t
            # 인물·공간은 0001 부터 있었다 — 0005 가 건드리지 않는다
            assert "attrs" in _columns(conn, "canon_characters")
            assert "attrs" in _columns(conn, "canon_spaces")
    finally:
        command.upgrade(cfg, "head")

    with engine.connect() as conn:
        for t in TABLES:
            cols = {c["name"]: c for c in sa.inspect(conn).get_columns(t)}
            assert "attrs" in cols and cols["attrs"]["nullable"], t
        assert "attrs" not in _columns(conn, "canon_foreshadowing")
    engine.dispose()
