# Glitch 통합본 (프론트 + 백엔드)

> 백엔드(FastAPI)가 `frontend/`를 같은 오리진 `/`로 정적 서빙한다. 프론트는 모든 데이터를
> 백엔드 API로 읽고 쓰며, 브라우저 저장소에는 **테마(모양·색상)와 사이드바 접힘만** 남긴다.
> 진행 상태의 진실은 서버의 `chapters.status` 하나다 — 프론트는 그걸 보여주기만 한다.
> API 계약은 [`docs/glitch_api_contract.md`](docs/glitch_api_contract.md).

## 폴더 구조

```
glitch_integrated/
├─ app/                       # 백엔드 (CLAUDE.md 의 레이어 규칙)
├─ alembic/                   # 마이그레이션
├─ ai_server/                 # AI(파이프라인) 서버 — 백엔드가 PIPELINE_MODE=remote 일 때 부른다
├─ tests/                     # 백엔드 테스트 (pytest)
├─ frontend/                  # 프론트 (빌드 없음, ES 모듈 그대로 서빙)
│  ├─ index.html · style.css · images/
│  ├─ script.js               #   화면 그리기·이벤트. 서버 데이터는 store.js 로만 읽고 쓴다
│  ├─ store.js                #   데이터 접근 한 곳: API 호출 + 메모리 캐시(열린 프로젝트만)
│  ├─ api.js                  #   계약서 엔드포인트 클라이언트. 401 → 토큰 1회 재교환 후 재시도
│  ├─ config.js               #   BASE_URL("" = 같은 오리진), 작업 창 폴링 주기
│  ├─ delta-view.js           #   canon_delta → 1차 탭 6분류(entity_key 유지), 모순 → 2차 카드, 상태 라벨
│  ├─ canon-view.js           #   시각화 탭 유일한 렌더러: 전체=canon, 회차=canon?chapter=N, 저장 전=canon_delta
│  ├─ task-tray.js            #   우측 하단 작업 창 — GET /jobs/active 폴링으로 진행·완료 표시
│  ├─ embedding-loader.js     #   전체 화면 로딩 오버레이 (분석 서버 연결 확인 중)
│  ├─ firebase-config.js      #   Firebase 초기화 (Auth 만)
│  └─ auth/
│     ├─ backend-auth.js      #   구글 로그인 ID 토큰 → POST /auth/firebase → JWT(sessionStorage)
│     └─ demo-auth.js         #   데모 로그인 스위치 (아래)
└─ INTEGRATION.md             # 이 문서
```

화면 ↔ API 대응은 계약서의 각 절에 **"화면: ○○"** 으로 적어 두었다.

## 실행

구성(저장소 기본, D17): DB = compose `db` 컨테이너(PostgreSQL 16, `127.0.0.1:5433`), Redis = compose
`redis` 컨테이너(`127.0.0.1:6379`, `.env`의 `REDIS_PASSWORD` 필수), 큐 = arq(`QUEUE_MODE=arq`).
네이티브 PostgreSQL을 쓰는 PC는 `.env`의 DB URL만 바꾼다(선택 — README "네이티브 PostgreSQL 사용").
처음 설치는 README "빠른 시작".

```
start_integrated.bat
```

이 스크립트가 ① `docker compose up -d db redis` ② 분석 워커 창
(`python -m arq app.workers.worker.WorkerSettings`) ③ `uvicorn --host 127.0.0.1 --port 8000` 을 띄운다.
손으로 띄울 때도 같다 (PowerShell, 저장소 루트):

```
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m arq app.workers.worker.WorkerSettings          # 창 하나
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000   # 다른 창
```

- ⚠️ 반드시 `--host 127.0.0.1`. 이 PC는 공인 IP 직결이라 `0.0.0.0` 이면 인터넷에 그대로 열린다.
- 접속 (서버 바인딩은 `127.0.0.1` 그대로 — `localhost` 접속도 그 바인딩으로 들어온다):
  - **구글 로그인:** <http://localhost:8000/> — Firebase 승인 도메인이 `localhost`라 `127.0.0.1`에서는 팝업이 거부된다.
  - **데모 로그인:** <http://127.0.0.1:8000/?demo=1> 또는 <http://localhost:8000/?demo=1>
  - API 문서 `/docs`.
- DB 직접 보기(로컬 전용): `docker compose --profile tools up -d adminer` → <http://127.0.0.1:8081> (README "DB 직접 보기")
- 마이그레이션: `.venv\Scripts\python.exe -m alembic upgrade head`
- 테스트: `.venv\Scripts\python.exe -m pytest -q`
- 분석 결과 없이 화면만 돌려볼 때: 서버와 워커 **둘 다** `PIPELINE_MODE=fake` 를 명령줄 환경변수로
  덧씌워 띄운다(`.env` 는 그대로). 워커가 파이프라인을 실행하므로 워커 쪽이 특히 중요하다.

## 데모 로그인 (구글 로그인 없이)

1. 백엔드 `.env`: `FIREBASE_MODE=fake` (서버 재시작)
2. 브라우저: <http://127.0.0.1:8000/?demo=1>(또는 `localhost`) → "시작하기" → 팝업 없이 데모 사용자
   (시드 계정 `cho@example.com`)로 로그인된다. 시작 화면에 "데모 로그인 모드" 배지가 보인다.

- `auth/demo-auth.js` 는 **기본 OFF**다(구글 로그인). `?demo=1` 이면 그 탭(sessionStorage) 동안 데모,
  `?demo=0` 이면 해제. (2026-07-29~10-13 에는 임시로 데모가 기본값이었다.)
- ⚠️ `FIREBASE_MODE=fake` 는 서버가 `fake:<email>[:<name>]` 토큰을 무검증으로 믿는 모드다 —
  **로컬/사설 데모 전용.** 공개 URL(터널 등)에 fake 모드를 열어두지 말 것.
- 페이지에 들어오면 항상 로그아웃 상태에서 시작한다(탭/창을 닫으면 로그아웃 요구사항).
  새로고침해도 데이터는 서버에 있으므로 다시 "시작하기"만 누르면 드라이브·회차·결과가 그대로이고,
  진행 중이던 분석은 로그인 직후 작업 창에 복원된다.
