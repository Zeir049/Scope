"""pytest 공용 fixture. ASGITransport로 실제 앱+DB에 붙는 통합 테스트.

(ASGITransport는 lifespan을 실행하지 않으므로 테스트 중 자동 시드는 안 돈다.)

테스트는 전용 DB(glitch_test)를 쓴다 — 실 DB(glitch_integrated)에 테스트
유저/프로젝트가 쌓이는 오염 방지. 아래 환경변수 주입은 pydantic-settings가
.env보다 환경변수를 우선하는 성질을 이용하므로, 반드시 app.* 임포트
(=Settings 인스턴스화)보다 먼저 실행돼야 한다.

접속 대상은 **앱이 실제로 쓰는 DB 서버를 그대로 따라간다**(.env의
DATABASE_URL_SYNC에서 호스트/포트/계정을 읽고 DB 이름만 glitch_test로 교체).
포트를 하드코딩하면 로컬 PG(5432) ↔ docker(5433)를 오갈 때마다 테스트가
깨진다 — 2026-09-10에 실제로 그렇게 깨졌다.
CI 등에서 다른 서버를 쓰려면 GLITCH_TEST_DSN 환경변수로 덮어쓴다.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

_TEST_DB = "glitch_test"
_FALLBACK_DSN = "postgresql://glitch:glitch@localhost:5432/glitch_integrated"


def _app_dsn() -> str:
    """앱이 보고 있는 DSN을 찾는다: 환경변수 → .env → 기본값."""
    override = os.environ.get("GLITCH_TEST_DSN")
    if override:
        return override

    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL_SYNC="):
                return line.split("=", 1)[1].strip()

    return _FALLBACK_DSN


_parts = urlsplit(_app_dsn().replace("+psycopg2", "").replace("+asyncpg", ""))
PG_HOST = _parts.hostname or "localhost"
PG_PORT = _parts.port or 5432
PG_USER = _parts.username or "glitch"
PG_PASSWORD = _parts.password or "glitch"

_PG_HOST = f"{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}"
os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{_PG_HOST}/{_TEST_DB}"
os.environ["DATABASE_URL_SYNC"] = f"postgresql+psycopg2://{_PG_HOST}/{_TEST_DB}"


def _app_redis_url() -> str:
    """앱이 보는 Redis 주소: 환경변수 → .env → 기본값."""
    if os.environ.get("REDIS_URL"):
        return os.environ["REDIS_URL"]
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("REDIS_URL="):
                return line.split("=", 1)[1].split("#", 1)[0].strip()
    return "redis://127.0.0.1:6379/0"


# arq 테스트(test_queue.py)는 같은 Redis 서버의 db 1 을 쓴다 — 개발용 db 0 에 키를 남기지 않게.
# (호스트·포트·인증은 앱 설정 그대로, db 번호만 교체)
os.environ["REDIS_URL"] = urlsplit(_app_redis_url())._replace(path="/1").geturl()
# 파이프라인은 항상 fake — 테스트가 외부 AI 서버(:8100)에 의존하면 안 된다.
# .env 가 remote 여도 여기서 덮어쓴다(2026-09-10: 이걸 안 해서 16개가 ConnectError로
# 깨졌다). remote 어댑터 자체는 glitch_ai/check_contract.py 가 검증한다.
os.environ["PIPELINE_MODE"] = "fake"
# 분석 작업은 서버 프로세스 안(inline)에서 실행 — Redis/워커 없이 테스트 가능.
# arq 경로 자체는 tests/test_queue.py 가 Redis가 있을 때만 검증한다.
os.environ["QUEUE_MODE"] = "inline"
# 레이트리밋 비활성 — 테스트는 같은 클라이언트로 수천 요청을 보내므로.
# 리밋 동작 자체는 tests/test_ratelimit.py 가 값을 바꿔 검증한다.
os.environ["RATE_LIMIT_PER_MINUTE"] = "0"


def _ensure_test_db() -> None:
    """glitch_test DB가 없으면 만들고, 스키마를 최신 마이그레이션으로 맞춘다."""
    import psycopg2

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD,
        dbname="postgres",
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB,))
        if cur.fetchone() is None:
            try:
                cur.execute(f'CREATE DATABASE "{_TEST_DB}"')
            except psycopg2.errors.InsufficientPrivilege as e:
                # docker 구성에서는 glitch 가 슈퍼유저라 그냥 됐지만, 로컬에
                # 설치한 PostgreSQL 에서는 보통 평범한 역할이라 권한이 없다.
                nl = chr(10)
                raise RuntimeError(
                    nl.join([
                        f"테스트 DB '{_TEST_DB}' 를 만들 권한이 없습니다"
                        f" ({PG_USER}@{PG_HOST}:{PG_PORT}).",
                        "슈퍼유저로 아래 중 하나를 한 번만 실행하세요:",
                        f'  psql -U postgres -p {PG_PORT} -c "ALTER ROLE'
                        f' {PG_USER} CREATEDB;"',
                        f'  psql -U postgres -p {PG_PORT} -c "CREATE DATABASE'
                        f' {_TEST_DB} OWNER {PG_USER};"',
                        "다른 서버를 쓰려면 GLITCH_TEST_DSN 으로 지정하세요.",
                    ])
                ) from e
    conn.close()

    from alembic import command
    from alembic.config import Config

    # alembic/env.py가 settings.database_url_sync(위에서 주입한 테스트 URL)를 쓴다
    command.upgrade(Config("alembic.ini"), "head")


_ensure_test_db()

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    """각 테스트는 pytest-asyncio가 새 이벤트 루프를 준다. 전역 async 엔진의
    asyncpg 커넥션은 루프에 묶이므로, 테스트마다 풀을 비워 다음 루프가
    새 커넥션을 받게 한다(= 'Event loop is closed' 방지)."""
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    sfx = uuid.uuid4().hex[:8]
    r = await client.post(
        "/auth/register",
        json={"email": f"u_{sfx}@x.com", "password": "secret123", "name": "Tester"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    r = await client.post("/projects", json={"name": "테스트작품"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]
