# Glitch (백엔드 몸통 + 프론트)

장편 서사 모순 탐지 서비스 **Glitch**. 이 저장소는 백엔드 게이트웨이(인증 / 프로젝트·회차 관리 /
원문 저장 / 파이프라인 중개 / 캐논 병합)와, 그 백엔드가 같은 오리진 `/`로 서빙하는 프론트(`frontend/`)를 담는다.

- 처음 읽을 문서: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (요청 흐름·상태 머신·결정 기록)
- API 계약(프론트 연동): [`docs/glitch_api_contract.md`](docs/glitch_api_contract.md)
- 코딩 규칙: [`CLAUDE.md`](CLAUDE.md) · 프론트 구조·데모 로그인: [`INTEGRATION.md`](INTEGRATION.md)

## 스택
Python 3.11+ · FastAPI(async) · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · arq(Redis) · 프론트는 빌드 없는 ES 모듈

## 빠른 시작 (Windows, Docker Desktop)

PostgreSQL을 따로 설치하지 않는다. DB(127.0.0.1:5433)와 Redis(127.0.0.1:6379)는 compose 컨테이너로 띄운다.

```powershell
# 1) 클론 + 가상환경 + 의존성
git clone <repo> glitch_integrated
cd glitch_integrated
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2) 환경변수 — 복사한 뒤 REDIS_PASSWORD 와 REDIS_URL 의 change-me 를 같은 값으로 바꾼다
copy .env.example .env
notepad .env

# 3) DB + Redis 컨테이너 (REDIS_PASSWORD 가 없으면 compose 가 기동을 거부한다)
docker compose up -d db redis

# 4) 마이그레이션
.\.venv\Scripts\python.exe -m alembic upgrade head

# 5) 분석 워커 + 서버 (창 두 개. 반드시 127.0.0.1 — 0.0.0.0 금지)
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m arq app.workers.worker.WorkerSettings
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

3~5단계는 `start_integrated.bat` 한 번으로 대신할 수 있다(db·redis 컨테이너 → 워커 창 → 서버).

- 접속 주소 (서버는 `127.0.0.1`에만 바인딩 — `localhost` 접속도 그 바인딩으로 들어온다):
  - **구글 로그인:** <http://localhost:8000/> — Firebase 승인 도메인이 `localhost`라 `127.0.0.1`에서는 팝업이 거부된다
  - **데모 로그인:** <http://127.0.0.1:8000/?demo=1> 또는 <http://localhost:8000/?demo=1>
  - API 문서 `/docs` · 상태 `/health`
- **데모 로그인**(구글 팝업 없이, `?demo=1` 옵트인): `.env`에서 `FIREBASE_MODE=fake`로 바꾸고 서버를 다시 띄운 뒤
  `?demo=1` 주소로 접속 → "시작하기". 시드 계정 `cho@example.com`으로 로그인된다. 탭을 닫거나 `?demo=0`이면 해제.
  fake 모드는 토큰을 검증하지 않으므로 **로컬 전용**(공개 URL 금지).
- `.env.example`은 `PIPELINE_MODE=fake`(고정 예시 결과)다. 실제 분석은 아래 "AI 서버까지 함께 돌리기".

### (선택) 네이티브 PostgreSQL 사용

호스트에 PostgreSQL이 이미 있으면 compose `db` 대신 쓸 수 있다. DB·계정을 만들고
`.env`의 `DATABASE_URL` / `DATABASE_URL_SYNC` 포트·이름만 바꾼다(예: `localhost:5432`).

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -c "CREATE USER glitch WITH PASSWORD 'glitch';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE glitch_integrated OWNER glitch;"
```

이때 `start_integrated.bat`이 띄우는 `db` 컨테이너는 쓰이지 않지만 127.0.0.1에만 열리므로 무해하다.
`docker compose up -d redis`만 띄워도 된다.

## 구조 (의존 방향: 위 → 아래)
```
app/api/         FastAPI 라우터. HTTP 입출력·검증만.
  app/service/   비즈니스 로직 · 트랜잭션 경계 · 파이프라인 호출.
    app/repository/  DB 접근(SQLAlchemy). SQL은 여기에만.
      app/models/    ORM 모델
app/schemas/     Pydantic 요청/응답 (ORM과 분리)
app/pipeline/    AnalysisPipeline 인터페이스 + fake/local/remote 구현
app/workers/     arq 큐·워커·작업(추출/검수)
frontend/        프론트 (store.js → api.js 로만 서버 데이터에 접근)
```
전체 파일 목록은 `CLAUDE.md` "폴더 구조".

## 파이프라인 교체 포인트
`PIPELINE_MODE=fake|local|remote`로 주입한다. 몸통은 `AnalysisPipeline`
(`extract_chapter` / `review_chapter` / `health`, `app/pipeline/interface.py`)만 알고,
remote 구현이 AI 서버의 `/extract` · `/review` · `/health`를 부른다.

## AI 서버까지 함께 돌리기 (`ai_server/`)
`PIPELINE_MODE=remote`면 몸통이 `ai_server/`(포트 8100)를 HTTP로 부른다.
AI 서버는 의존성이 따로라(torch 등) **venv를 따로** 만든다. 자세한 내용은 [ai_server/README.md](ai_server/README.md).

```powershell
# 1) AI 서버 venv + 의존성 (torch·BGE-M3 포함이라 처음엔 오래 걸린다)
cd ai_server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env        # 기본 echo 모드 = LLM 호출 없음, API 키 불필요
.\run.bat                     # → http://127.0.0.1:8100/health
cd ..

# 2) 몸통 .env 에서 AI 서버를 보게 한다
#    PIPELINE_MODE=remote
#    PIPELINE_REMOTE_URL=http://127.0.0.1:8100

# 3) 몸통 워커·서버를 다시 띄운다 (위 빠른 시작 5번) → http://127.0.0.1:8000/?demo=1
```

- ⚠️ **echo 모드(기본값)는 원고와 무관한 고정 샘플을 돌려준다.** 화면엔 그럴듯한 결과가 나오지만 실제 분석이 아니다.
- 실제 분석(`EXTRACT_MODE=llm`, `REVIEW_MODE=llm`)은 `ai_server/.env`에 `ANTHROPIC_API_KEY`가 필요하고 **회차당 Claude 2회 호출 비용**이 든다.
- torch 설치가 부담되면 `requirements.txt`의 아래 3줄(sentence-transformers·torch·numpy)을 빼고 설치한 뒤
  `ai_server/.env`에 `EMBEDDING_MODE=hash` (배선 확인용, 의미 유사도 없음).
- NVIDIA GPU가 있으면 torch를 CUDA 빌드로 먼저 깔면 임베딩이 빠르다:
  `.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu126`
- AI 서버 단위 테스트: `cd ai_server; .\.venv\Scripts\python.exe -m unittest discover -s tests -t .`

## 기능 플래그 (켜고 끄기)
`.env`에서 끄면 해당 API가 OpenAPI에서 통째로 사라진다:
`ENABLE_SUBSCRIPTION` · `ENABLE_SHARING` · `ENABLE_CHAT` · `ENABLE_NOTIFICATIONS` · `ENABLE_FIREBASE_AUTH` · `ENABLE_SMOKE`

## 교체 가능한 인프라 (구현체만 갈아끼움)
| 경계 | 설정 | 지금 | 나중 |
|------|------|------|------|
| 문서 파서 | (레지스트리 `app/parsing/`) | txt/md/docx/pdf | 확장자 추가 |
| 메일 발송 | `EMAIL_MODE` | console(로그) | smtp |
| 파일 저장 | `STORAGE_MODE` | local(`/uploads`) | s3 |
| 채팅 어시스턴트 | `CHAT_MODE` | fake | remote |
| 분석 파이프라인 | `PIPELINE_MODE` | fake | remote/local |
| 작업 큐 | `QUEUE_MODE` | arq(Redis) | (inline은 테스트 전용) |

## 데모 계정 (시드)
`SEED_ON_STARTUP=true`면 첫 기동 시 자동 주입:
- 이메일 `cho@example.com` / 비밀번호 `glitch123` (plan: pro)
- 프로젝트 "금도끼 은도끼" — 1~3화 저장됨, 4화 신규

## DB 직접 보기 (Adminer, 로컬 전용)
`docker compose --profile tools up -d adminer` → <http://127.0.0.1:8081> (서버 `db`, 사용자·비밀번호 `glitch`, DB `glitch_integrated`).
compose `db` 컨테이너용이다. 다 보면
`docker compose --profile tools stop adminer`. tools 프로필이라 `docker compose up -d`에는 뜨지 않는다. 터널로 열지 않는다.

## 백업
`backup.bat` — `.env`의 `DATABASE_URL_SYNC`가 가리키는 DB를 `backups\glitch_<시각>.sql`로 덤프한다.

## 테스트
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
테스트는 Redis db 1을 쓴다(`docker compose up -d redis` 필요).

## 브랜치
이 코드의 기준 브랜치는 `backend`다. 작업 브랜치(`fusion-*` 등)는 `backend`에서 만들고 `backend`로 PR을 연다.
(`main`·`AI`·개인 브랜치는 팀 원격의 다른 작업 줄기로, 지금은 `backend`의 조상이 아니다.)
