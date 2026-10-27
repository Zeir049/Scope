"""마이그레이션 0004 왕복 + 기존 행 채우기 + 모델/DB 일치 검증.

upgrade head → downgrade 0003 → (0003 스키마에 회차 행 삽입) → upgrade head 순서로
돌려서, 0004 의 backfill(updated_at = created_at, content_hash = sha256(raw_text))이
앱의 해시 계산과 같은 값을 내는지 확인한다. 마지막에 alembic check 로 모델과
마이그레이션 결과가 어긋나지 않는지도 본다.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.service.chapter_service import content_hash


def _cfg() -> Config:
    return Config("alembic.ini")


def _columns(conn, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_0004_downgrade_upgrade_and_backfill():
    cfg = _cfg()
    engine = sa.create_engine(settings.database_url_sync)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0003_visual_json")
    try:
        with engine.begin() as conn:
            cols = _columns(conn, "chapters")
            assert not {"kind", "updated_at", "content_hash"} & cols
            assert "status" not in _columns(conn, "contradictions")

            # 0003 스키마에 기존 데이터처럼 행을 넣는다
            uid, pid, cid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            conn.execute(
                sa.text("INSERT INTO users (id, email, password_hash, plan) VALUES (:i, :e, 'x', 'free')"),
                {"i": uid, "e": f"mig_{uid.hex[:8]}@x.com"},
            )
            conn.execute(
                sa.text("INSERT INTO projects (id, owner_id, name) VALUES (:i, :o, 'mig')"),
                {"i": pid, "o": uid},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO chapters (id, project_id, chapter_no, raw_text, status, created_at)"
                    " VALUES (:i, :p, 1, :t, 'saved', '2026-01-02T03:04:05+00')"
                ),
                {"i": cid, "p": pid, "t": "한글 원문 ✓ 테스트"},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO contradictions (id, chapter_id, type) VALUES (:i, :c, 'character')"
                ),
                {"i": uuid.uuid4(), "c": cid},
            )
    finally:
        command.upgrade(cfg, "head")

    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT kind, updated_at, created_at, content_hash FROM chapters WHERE id = :i"),
            {"i": cid},
        ).one()
        assert row.kind == "narrative"
        assert row.updated_at == row.created_at
        assert row.content_hash == content_hash("한글 원문 ✓ 테스트")
        status = conn.execute(
            sa.text("SELECT status FROM contradictions WHERE chapter_id = :c"), {"c": cid}
        ).scalar_one()
        assert status == "pending"
        conn.execute(sa.text("DELETE FROM users WHERE id = :i"), {"i": uid})  # CASCADE 정리
    engine.dispose()


# alembic 체인 밖에서 따로 만드는 테이블 (ENABLE_SMOKE 일 때 app.smoke 가 메타데이터에 등록)
_OUTSIDE_ALEMBIC = {"smoke_checks"}


def _outside_alembic(diff) -> bool:
    for obj in (diff if isinstance(diff, list) else [diff]):
        for part in obj[1:] if isinstance(obj, tuple) else ():
            table = getattr(part, "table", part)
            if getattr(table, "name", None) in _OUTSIDE_ALEMBIC:
                return True
    return False


def test_models_match_migrations():
    """alembic check 와 같은 비교 — 모델 선언과 마이그레이션 결과가 같아야 한다."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base

    engine = sa.create_engine(settings.database_url_sync)
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    diffs = [d for d in diffs if not _outside_alembic(d)]
    assert diffs == []
