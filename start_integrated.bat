@echo off
rem Glitch integrated (frontend + backend) - http://localhost:8000/
rem %~dp0 = this script's folder, so it works wherever the repo is cloned
cd /d %~dp0
set PYTHONUTF8=1

rem -- Containers (Docker Desktop): db = PostgreSQL 16 on 127.0.0.1:5433 (the repo
rem    default DB, see .env.example) and redis = arq analysis queue on 127.0.0.1:6379.
rem    A PC that points .env at a native PostgreSQL may leave db running unused:
rem    it is bound to 127.0.0.1 only, so it is harmless. --
rem Docker Desktop app must be running (docker.exe is on the user PATH).
rem NB: keep this file ASCII-only -- cmd misparses Korean comments (no chcp).
rem The old "wsl -d Ubuntu -- docker compose" route was a SEPARATE engine
rem (Docker CE inside Ubuntu) and spawned a duplicate DB; do not revive it.
where docker >nul 2>&1
if errorlevel 1 set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%PATH%"
docker info >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ERROR] Docker Desktop is not running - db/redis cannot start.
  echo         Launch Docker Desktop, wait for it to finish starting,
  echo         then run this script again.
  echo.
  pause
  exit /b 1
)
docker compose up -d db redis

rem -- Analysis worker (arq) in its own window. Required when QUEUE_MODE=arq
rem    (.env). It pulls analysis jobs from Redis so the API server never
rem    blocks on long LLM calls and queued jobs survive an API restart.
start "Glitch Worker" cmd /k ".venv\Scripts\python.exe -m arq app.workers.worker.WorkerSettings"

.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
