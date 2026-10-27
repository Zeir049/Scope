"""로깅 설정 — 콘솔 + 회전 파일(logs/<이름>.log).

공개 테스트 중 "아까 안 됐어요"를 추적할 수 있게 모든 로그(uvicorn 접근
로그 포함)를 파일로도 남긴다. API 서버와 워커는 프로세스가 다르므로
각자 파일(api.log / worker.log)을 갖는다. 5MB × 3개 회전.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FMT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(name: str) -> None:
    """루트 로거에 콘솔 + 회전 파일 핸들러를 단다 (중복 호출 안전)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(_FMT)

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    target = str(log_dir / f"{name}.log")

    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "baseFilename", "").endswith(f"{name}.log")
        for h in root.handlers
    ):
        fh = logging.handlers.RotatingFileHandler(
            target, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if not any(
        type(h) is logging.StreamHandler for h in root.handlers  # noqa: E721
    ):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # uvicorn 로거들이 자기 핸들러만 쓰고 전파를 끊어두므로,
    # 루트로 전파시켜 접근 로그까지 파일에 남긴다.
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(logger_name)
        lg.handlers = []
        lg.propagate = True
