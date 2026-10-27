@echo off
REM Glitch LLM pipeline server -- http://127.0.0.1:8100
REM NB: keep this file ASCII-only -- cmd misparses Korean comments (no chcp).
REM     There is no web UI here. The site is the backend at :8000.
REM     Endpoints: /health  /health/llm  /extract  /review  /docs
cd /d %~dp0
set PYTHONUTF8=1
.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8100 --reload
