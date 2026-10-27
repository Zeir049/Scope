# CLAUDE.md — Glitch 백엔드

> 이 파일은 백엔드 프로젝트 루트에 둔다. Claude Code가 매 작업마다 자동으로 읽는다.
> 상세 기능 명세는 `docs/glitch_backend_spec.md`, API·상태값의 최신은 `docs/glitch_api_contract.md`,
> 전체 그림은 `docs/ARCHITECTURE.md`(처음 읽을 문서). 이 문서는 **"어떻게 짜야 하는가"(규칙)** 만 다룬다.

---

## 프로젝트 한 줄 요약

장편 서사의 세계관·설정 모순을 잡는 AI 서비스 **Glitch** 의 **백엔드 몸통(게이트웨이)**.
역할: 인증 / 프로젝트·회차 관리 / 원문 저장 / 파이프라인 호출 / 결과 저장(캐논 병합).
**모순 검출 LLM 로직은 이 코드베이스의 책임이 아니다** — 인터페이스 뒤의 별도 영역.

## 스택

- Python 3.11+ · FastAPI · async/await
- PostgreSQL · SQLAlchemy(2.0 스타일) · Alembic(마이그레이션)
- 작업 큐: arq + Redis (`QUEUE_MODE=arq`, 분석은 워커 프로세스에서 비동기. `inline`은 테스트 전용)
- 의존성 관리: `pyproject.toml` + pip (`pip install -e .[dev]`, 가상환경 `.venv`)

---

## 핵심 불변 원칙 (절대 어기지 말 것)

1. **파이프라인은 인터페이스로만 호출한다.**
   `AnalysisPipeline` 프로토콜 외의 방법으로 LLM/파이프라인을 직접 부르지 않는다.
   구현체(Remote/Local/Fake)는 설정(`PIPELINE_MODE`)으로 주입한다.
   서비스 코드 어디에도 httpx URL이나 LLM SDK가 직접 등장하면 안 된다.

2. **캐논은 덮어쓰지 않는다 (append-only, 버전 보관).**
   설정이 바뀌면 옛 행을 `is_current=false`로 표시하고 새 행을 INSERT 한다.
   `DELETE`/`UPDATE ... SET item=...`로 캐논 항목 내용을 갈아엎지 않는다.

3. **캐논 병합은 트랜잭션 안에서 딱 한 번.**
   `chapters.status = saved` 전환과 canon_* 병합은 같은 트랜잭션. 중복 저장은 멱등 처리.

4. **상태(status)는 단일 진실 원천.**
   `chapters.status` (uploaded→extracting→extracted→reviewing→reviewed→saved, 어느 단계든 failed, 재검수는 saved→reviewing) 외의 곳에 진행 상태를 중복 저장하지 않는다.

5. **소유권 검사는 항상.**
   모든 project/chapter 접근은 `owner_id == 현재 사용자` 를 먼저 검증한다.

---

## 레이어 구조 (의존 방향: 위 → 아래만)

```
api/         FastAPI 라우터. HTTP 입출력·검증만. 비즈니스 로직 금지.
  └─ service/   비즈니스 로직. 트랜잭션 경계. 파이프라인 인터페이스 호출.
       └─ repository/  DB 접근(SQLAlchemy). SQL은 여기에만.
            └─ models/   ORM 모델 + Pydantic 스키마
```

- 라우터는 service만 부른다. 라우터에서 직접 DB 세션을 쿼리하지 않는다.
- service는 repository를 통해서만 DB에 접근한다. service에 raw SQL 금지.
- 파이프라인 호출은 service 레이어에서만. 주입받은 `AnalysisPipeline`을 통해서.

## 폴더 구조

저장소 루트가 곧 백엔드 루트다(`backend/` 폴더는 없다). 프론트는 `frontend/`를 같은 오리진 `/`로 정적 서빙.

```
app/
  main.py        앱 조립(라우터 등록, 프론트 정적 서빙)   seed.py(데모 시드: cho@example.com)
  core/          config.py(Settings)  db.py(세션)  security.py(인증/해시)  exceptions.py  logging.py  ratelimit.py
  api/           auth.py  firebase_auth.py  projects.py  chapters.py  canon.py  jobs.py  pipeline.py  deps.py
                 (기능 플래그: subscription.py  share.py  chat.py  notifications.py)
  service/       auth_service.py  project_service.py  chapter_service.py  canon_service.py  job_service.py
                 pipeline_service.py  ownership.py  (+ 플래그 기능 service)
  repository/    user_repo.py  project_repo.py  chapter_repo.py  analysis_repo.py  canon_repo.py  reset_repo.py  (+ 플래그 기능)
  models/        user.py  project.py  chapter.py  analysis.py  canon.py  auth_reset.py  base.py  (+ 플래그 기능)
  schemas/       Pydantic 요청/응답 모델 (ORM 모델과 분리) — job.py pipeline.py 포함
  pipeline/      interface.py(Protocol·스키마)  factory.py  remote.py  local.py  fake.py(+fake_visual.json)  transform.py
  workers/       queue.py(enqueue)  worker.py(arq WorkerSettings)  tasks.py(추출/검수 작업)
  parsing/       registry.py(txt/md/docx/pdf → 텍스트)
  storage/       storage.py(썸네일 저장)
  firebase/      verifier.py(Firebase ID 토큰 검증 google|fake)
  chat/ email/ smoke/   선택 기능·임시 스모크
alembic/         마이그레이션 0001~0005
tests/
ai_server/       AI(파이프라인) 서버, 포트 8100 — 몸통은 /extract /review /health 만 부른다
frontend/        index.html style.css script.js store.js api.js config.js delta-view.js canon-view.js task-tray.js embedding-loader.js firebase-config.js auth/(backend-auth.js demo-auth.js)
docs/            ARCHITECTURE.md  glitch_api_contract.md  glitch_backend_spec.md  archive/(옛 문서)
```

---

## 코딩 컨벤션

- **타입 힌트 필수.** 모든 함수 시그니처에 타입. Pydantic으로 경계 검증.
- **async 일관성.** I/O(DB·HTTP)는 async. 동기/비동기 혼용 주의.
- **네이밍**: 함수·변수 snake_case, 클래스 PascalCase, 상수 UPPER_SNAKE. 라우트는 명사 복수형(`/projects`, `/chapters`).
- **요청/응답 모델은 ORM 모델과 분리.** ORM 객체를 그대로 직렬화해 반환하지 않는다(스키마로 변환).
- **에러 처리**: 도메인 예외(`NotFoundError`, `PermissionError`, `ConflictError`)를 정의하고, 전역 핸들러에서 HTTP 상태코드로 매핑. 라우터에서 try/except 남발 금지.
- **설정**: 모든 환경 의존값은 `core/config.py`의 Settings(pydantic-settings)로. 코드에 하드코딩·비밀값 금지.
- **로깅**: print 금지, 표준 logging 사용. 외부 호출(파이프라인)·상태 전환은 로그를 남긴다.

## DB / 마이그레이션 규칙

- 스키마 변경은 **반드시 Alembic 마이그레이션**으로. 모델만 고치고 끝내지 않는다.
- 캐논 쿼리: 현재 상태는 `WHERE is_current = true`. 시점 조회는 `source_chapter`/`superseded_at_chapter` 범위로.
- N+1 주의: 관계 로딩은 명시적으로(selectinload 등).

## LLM 파이프라인 경계

- 계약(`pipeline/interface.py`의 `AnalysisPipeline`, 2단계):
  - `async def extract_chapter(chapter_text, canon, title=None, *, chapter_no=None) -> ExtractionOutput` — 1차 추출(canon_delta)
  - `async def review_chapter(chapter_text, canon, delta, title=None, *, chapter_no=None) -> ReviewOutput` — 2차 검수(모순)
  - `async def health() -> PipelineHealth` — 연결 사전 점검(LLM 호출 없음)
  - 구현체는 `PIPELINE_MODE=fake|local|remote|replay`. remote는 AI 서버의 `/extract`·`/review`·`/health`를 부른다.
    replay는 시연용 — `pipeline/replay_data/chapter_N.json`(AI 응답을 미리 만든 것, `scripts/build_replay_data.py`)을 회차 번호로 돌려준다.
- 몸통의 일: 저장된 회차로 `CanonSnapshot` 구성(검수는 N-1화 시점) → 넘김 → 추출 결과 `canon_delta`를 저장 시(save) 캐논에 병합.
- 파이프라인의 일: 모순 검출·구조화. 몸통은 그 내부를 모른다.
- 입출력 JSON 스키마는 `pipeline/interface.py`에 Pydantic으로 단일 정의. 양쪽이 이걸 공유한다.

## 테스트

- service 레이어는 `FakePipeline`으로 파이프라인 없이 단위 테스트.
- 각 API는 정상 + 권한 위반 + 미존재 케이스를 최소한으로 커버.
- 캐논 병합은 "버전이 쌓이는지 / is_current가 1개만 유지되는지"를 반드시 테스트.

## 작업 시 주의

- 새 기능 추가 전 `glitch_backend_spec.md`의 해당 화면·API 절을 먼저 확인한다.
- 위 "핵심 불변 원칙" 5개를 위반하는 코드는 작성하지 않는다. 부득이하면 먼저 사용자에게 묻는다.
- 큰 변경은 작은 단위로 나눠 커밋. 한 PR에 마이그레이션 + 모델 + service + 테스트를 함께.
- 이 PC는 공인 IP 직결이다 — 서버·컨테이너는 `127.0.0.1`에만 바인딩한다(`--host 0.0.0.0`, compose 포트 접두 생략 금지).
