@echo off
REM ----------------------------------------------------------------------
REM  Glitch public test launcher (backend + Cloudflare quick tunnels)
REM  Korean guide: TUNNEL_GUIDE.md (same folder)
REM
REM  KEEP THIS FILE ASCII-ONLY. Korean text in .bat files gets misparsed
REM  by cmd depending on the console codepage (broke twice on 2026-07-29).
REM ----------------------------------------------------------------------
cd /d "%~dp0"

REM Containers: db (PostgreSQL 16, 127.0.0.1:5433, repo default DB) + redis (arq
REM queue, 127.0.0.1:6379). Both loopback-only; only the web app goes out via the tunnel.
echo [1/3] Starting db + redis containers...
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

echo [2/3] Starting backend on 127.0.0.1:8000 (loopback only; cloudflared proxies it) + analysis worker...
REM NB: PYTHONUTF8 is set here (inherited by the started windows). Do NOT use
REM "set PYTHONUTF8=1 && ..." inside the start command: cmd includes the
REM space before && in the value ("1 "), which is a fatal error for Python.
set PYTHONUTF8=1
start "Glitch Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
REM Analysis worker (arq): pulls jobs from Redis. Required when QUEUE_MODE=arq.
start "Glitch Worker" cmd /k ".venv\Scripts\python.exe -m arq app.workers.worker.WorkerSettings"

echo       Waiting 5s for backend startup...
timeout /t 5 >nul

echo [3/3] Starting Cloudflare tunnel (web, port 8000)...
start "Glitch Tunnel" cmd /k "cloudflared tunnel --url http://127.0.0.1:8000"

echo.
echo ----------------------------------------------------------------------
echo  Done. Three windows are now open ([Glitch Worker] runs the analysis jobs).
echo   1) [Glitch Tunnel] window: find https://xxxx.trycloudflare.com
echo      - that URL         = web UI
echo      - that URL + /docs = API docs (Swagger)
echo      - share the URL as is (Google sign-in; do not add ?demo=1)
echo      - NEVER open the tunnel with FIREBASE_MODE=fake in .env (no token check)
echo   2) To test share/password-reset links, put the web tunnel URL
echo      into PUBLIC_BASE_URL in .env, then restart [Glitch Backend].
echo.
echo  Full Korean guide: TUNNEL_GUIDE.md
echo ----------------------------------------------------------------------
pause
