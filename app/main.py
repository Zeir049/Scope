"""FastAPI 앱 조립 지점.

레이어 규칙(CLAUDE.md): 라우터는 service만 호출. 여기서는 앱 구성만.
기본 라우터(auth/projects/chapters/canon/pipeline/jobs) + 기능 플래그 라우터 + 프론트 정적 서빙(맨 마지막).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.ratelimit import register_rate_limit

setup_logging("api")  # 콘솔 + logs/api.log (uvicorn 접근 로그 포함)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 데모 시드 주입(설정 켜져 있고 아직 없을 때만)
    if settings.seed_on_startup:
        from app.seed import run_seed

        try:
            await run_seed()
        except Exception:  # noqa: BLE001 - 시드 실패가 앱 기동을 막지 않도록
            logger.exception("seed on startup failed")
    # ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 이 블록 삭제. app/smoke/README.md 참조
    if settings.enable_smoke:
        from app.smoke.table import ensure_smoke_table

        await ensure_smoke_table()
    yield


app = FastAPI(
    title="Glitch Backend",
    version="0.1.0",
    description="장편 서사 모순 탐지 — 백엔드 몸통(게이트웨이)",
    lifespan=lifespan,
)

# CORS — 프론트 도메인 허용 (계약서 5장 체크리스트)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
register_rate_limit(app)  # IP별 분당 요청 상한 (공개 터널 보호, 설정으로 조절)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "pipeline_mode": settings.pipeline_mode,
        "queue_mode": settings.queue_mode,
    }


# ── 정적 파일 마운트 ────────────────────────────────────────
# 업로드 파일(썸네일 등, STORAGE_MODE=local) → /uploads
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_upload_root = Path(settings.upload_dir)
_upload_root.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_upload_root)), name="uploads")

# ── 라우터 등록 ──────────────────────────────────────────────
from app.api import auth, canon, chapters, jobs, pipeline, projects  # noqa: E402

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(chapters.router)
app.include_router(canon.router)
app.include_router(pipeline.router)
app.include_router(jobs.router)

# 선택 기능: 기능 플래그가 켜져 있을 때만 라우터 등록(끄면 API 자체가 사라짐)
if settings.enable_firebase_auth:
    from app.api import firebase_auth  # noqa: E402

    app.include_router(firebase_auth.router)
if settings.enable_subscription:
    from app.api import subscription  # noqa: E402

    app.include_router(subscription.router)
if settings.enable_sharing:
    from app.api import share  # noqa: E402

    app.include_router(share.router)
if settings.enable_chat:
    from app.api import chat  # noqa: E402

    app.include_router(chat.router)
if settings.enable_notifications:
    from app.api import notifications  # noqa: E402

    app.include_router(notifications.router)

# ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 이 블록 삭제. app/smoke/README.md 참조
if settings.enable_smoke:
    from app.smoke.router import router as smoke_router  # noqa: E402

    app.include_router(smoke_router)

# ── 프론트엔드(정적 SPA) 서빙 ─────────────────────────────────
# 백엔드와 같은 오리진에서 UI를 제공 → CORS 불필요, 터널/배포 시 URL 하나로 통일.
# 반드시 모든 API 라우터 등록 뒤에 마운트해야 API 경로(/auth, /projects, /docs...)가 우선한다.


class _NoCacheStaticFiles(StaticFiles):
    """정적 파일을 캐시하지 않게 한다.

    개발/데모 중 프론트 파일을 고쳐도 브라우저가 옛 JS/CSS를 캐시해
    (예: 옛 기본화면이 계속 뜨는) 문제를 막는다. 정식 배포 시 캐시 전략은 별도로.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount(
        "/",
        _NoCacheStaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )
