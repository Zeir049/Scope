@echo off
REM ----------------------------------------------------------------------
REM  DB backup: dumps the database that .env points at (DATABASE_URL_SYNC,
REM  read through app.core.config) to backups\glitch_YYYYMMDD_HHMMSS.sql
REM  (plain SQL, UTF-8). Works for both the compose db (127.0.0.1:5433,
REM  repo default) and a native PostgreSQL (e.g. localhost:5432).
REM
REM  pg_dump: uses a local pg_dump.exe (PATH or PostgreSQL 16 install dir);
REM  if none is found, falls back to pg_dump inside the glitch-db container
REM  (only valid when .env points at the compose db).
REM
REM  Run this before/after demo sessions or risky operations.
REM
REM  RESTORE (into a fresh/empty DB): psql "<same URL>" -f backups\glitch_....sql
REM    compose db:  docker exec -i glitch-db psql -U glitch -d glitch_integrated ^
REM                   < backups\glitch_YYYYMMDD_HHMMSS.sql
REM
REM  KEEP THIS FILE ASCII-ONLY (cmd misparses Korean in .bat files).
REM ----------------------------------------------------------------------
cd /d "%~dp0"
set PYTHONUTF8=1

REM libpq URL from settings (drops the "+psycopg2" driver suffix)
for /f "usebackq delims=" %%u in (`.venv\Scripts\python.exe -c "from app.core.config import settings; print(settings.database_url_sync.replace('+psycopg2', ''))"`) do set "DBURL=%%u"
if not defined DBURL (
  echo [ERROR] Could not read DATABASE_URL_SYNC from .env via app.core.config.
  pause
  exit /b 1
)

if not exist backups mkdir backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
set "OUT=backups\glitch_%TS%.sql"

set "PGDUMP="
for /f "delims=" %%p in ('where pg_dump 2^>nul') do if not defined PGDUMP set "PGDUMP=%%p"
if not defined PGDUMP if exist "%ProgramFiles%\PostgreSQL\16\bin\pg_dump.exe" set "PGDUMP=%ProgramFiles%\PostgreSQL\16\bin\pg_dump.exe"

if defined PGDUMP (
  echo Dumping the .env database with local pg_dump to %OUT% ...
  "%PGDUMP%" --dbname="%DBURL%" --clean --if-exists --encoding=UTF8 -f "%OUT%"
) else (
  echo No local pg_dump found - using the glitch-db container ^(compose db^) to %OUT% ...
  where docker >nul 2>&1
  if errorlevel 1 set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%PATH%"
  docker exec glitch-db pg_dump -U glitch -d glitch_integrated --clean --if-exists > "%OUT%"
)
if errorlevel 1 (
  echo [ERROR] pg_dump failed. Is the database in .env running?
  del "%OUT%" 2>nul
  pause
  exit /b 1
)

for %%A in ("%OUT%") do echo Done: %%~fA (%%~zA bytes)
pause
