"""IP별 슬라이딩 윈도 레이트리밋 (인메모리) — 공개 터널 데모 보호용.

- 일반 요청: RATE_LIMIT_PER_MINUTE (기본 240/분), 0이면 비활성.
- /auth/* : RATE_LIMIT_AUTH_PER_MINUTE (기본 30/분) — 무차별 대입 방지.
- cloudflared 터널을 거치면 모든 요청의 소스 IP가 127.0.0.1이므로,
  CF-Connecting-IP 헤더가 있으면 그것을 클라이언트 식별자로 쓴다.
- 인메모리라 프로세스별로 따로 센다 — 단일 서버 데모엔 충분, 분산 시 Redis로 교체.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)
_last_sweep = 0.0


def _client_key(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )


def reset_state() -> None:
    """테스트용: 카운터 초기화."""
    _hits.clear()


def register_rate_limit(app: FastAPI) -> None:
    @app.middleware("http")
    async def rate_limit(request: Request, call_next):  # noqa: ANN001, ANN202
        limit = settings.rate_limit_per_minute
        if limit <= 0:
            return await call_next(request)

        now = time.monotonic()
        global _last_sweep
        if now - _last_sweep > 60:  # 낡은 클라이언트 키 청소
            _last_sweep = now
            stale = [k for k, dq in _hits.items() if not dq or now - dq[-1] > 120]
            for k in stale:
                _hits.pop(k, None)

        is_auth = request.url.path.startswith("/auth")
        effective = settings.rate_limit_auth_per_minute if is_auth else limit
        dq = _hits[f"{_client_key(request)}:{'auth' if is_auth else 'all'}"]
        cutoff = now - 60
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= effective:
            return JSONResponse(
                status_code=429,
                content={"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."},
            )
        dq.append(now)
        return await call_next(request)
