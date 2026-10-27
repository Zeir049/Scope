# Glitch AI 서버 설명서

> 작성 2026-08-30 · 대상 `C:\glitch_ai` · 포트 8100
> **2026-10-05: 저장소의 `ai_server/` 로 옮겼다.** 아래 본문의 `C:\glitch_ai` 는 `ai_server/`,
> `C:\glitch_integrated` 는 저장소 루트로 읽는다.
> 이 문서는 **"이게 뭐고 어떻게 동작하는가"** 를 설명한다.
> 실행 방법과 명령어는 [README.md](README.md) 를 본다.
>
> **2026-10-03 변경:** llm 모드 내부를 `scope_ai/`(AI 파트 원본)로 교체했다.
> `prompt/`·`server/llm.py` 의 run_extract/run_review 는 없어졌고, 5~9절의 프롬프트·
> stateless·ERS 설명은 교체 전 기준이다. 현재 구조는 README 의 "모드"·"원칙" 절과
> `server/scope_bridge.py` 머리 주석을 본다. 교체 전 사본은 작성자 PC 의 `C:\glitch_ai_backup_20261003` 에만 있다.

---

## 1. 한 줄 요약

장편 서사의 설정 모순을 잡는 서비스 **Glitch** 에서, **LLM 분석만 담당하는 별도 서버**.
백엔드 몸통(`C:\glitch_integrated`, 포트 8000)이 HTTP 로 호출한다.

```
프론트 ──▶ 몸통 :8000 ──HTTP/JSON──▶ AI 서버 :8100 ──▶ api.anthropic.com
                  ▲                          │
                  └────── rich JSON ─────────┘
```

## 2. 왜 별도 서버인가

몸통의 `CLAUDE.md` 불변원칙 1: **"모순 검출 LLM 로직은 몸통의 책임이 아니다."**
몸통은 인증·저장·캐논 병합만 하고, LLM 은 인터페이스 뒤의 별도 영역이다.

같은 프로세스에 넣는 선택지(`PIPELINE_MODE=local`)도 열려 있지만 별도 서버를 골랐다.

| | 이유 |
|---|---|
| 의존성 격리 | 나중에 붙일 BGE-M3 는 ~2GB. 웹 백엔드에 얹으면 기동이 느려진다 |
| 팀 분리 | 몸통과 LLM 담당이 다르다. 저장소·배포를 나누면 충돌이 적다 |
| 재시작 독립 | 프롬프트만 고칠 때 API 서버를 내릴 필요가 없다 |

대가는 "띄울 프로세스가 2개"인 것뿐이다.

## 3. 계약 — 이것만 지키면 나머지는 자유

두 서버는 **코드도 DB 도 공유하지 않는다.** 오가는 것은 JSON 뿐이다.
계약은 `glitch_integrated/app/pipeline/interface.py` **한 파일에만** 정의돼 있고,
이 서버의 `server/schemas.py` 가 그것을 미러한다.

> 몸통의 `interface.py` 가 바뀌면 `server/schemas.py` 도 같이 바꿔야 한다.
> 이것이 두 저장소 사이의 유일한 결합 지점이다.

### `POST /extract` — 1차 추출

원문에서 6기준 구조화 데이터를 뽑는다. **모순 판정은 하지 않는다.**

요청:

```json
{ "chapter_text": "s#1. 하늘도시 아르카, 새벽\n아르카에서는 누구도…",
  "canon": { "project_id": "…", "up_to_chapter": 0,
             "worldview": [], "characters": [], "relations": [],
             "timeline": [], "spaces": [], "events": [], "foreshadowing": [] },
  "title": "1화" }
```

응답 — Claude 가 준 rich JSON(prompt_result_1 포맷)을 **가공 없이 그대로**:

```json
{ "worldview_rules": [ { "rule_id": "RULE_001", "content": "…",
                         "source_text": "…", "certainty": "explicit" } ],
  "characters":      [ { "character_id": "CHAR_001", "name": "연우",
                         "traits": [...], "relationships": [...] } ],
  "events": [...], "times": [...], "locations": [...] }
```

변환은 몸통이 한다. `looks_like_visual_json()` 이 이 포맷을 알아보고
`visual_to_canon_delta()` 로 `CanonDelta` 를 만든다. 원본은 통째로
`analysis_results.visual_json` 에 보존돼 `GET /visual` 로 프론트 시각화에 내려간다.
(`raw_output` 은 실패 기록 전용이다 — 마이그레이션 `0003_visual_json` 에서 분리됐다.)

**`entity_key` 는 Claude 가 준 ID(`RULE_001`, `CHAR_001`)를 그대로 쓴다.**
그래서 같은 회차를 다시 분석해도 같은 키가 나오고, 캐논 병합이 멱등이다.

### `POST /review` — 2차 검수

기존 캐논 + 작가가 확정한 이번 회차 추출물을 대조해 모순을 찾는다.
`delta` 가 추가로 온다.

응답 — **스키마가 고정이다:**

```json
{ "contradictions": [ {
    "span": { "start": 12, "end": 47, "quote": "원문에서 그대로 복사한 문장" },
    "conflict_ref": { "chapter_no": 1, "quote": "충돌하는 기존 설정" },
    "type": "setting",
    "explanation": "무엇과 무엇이 어떻게 어긋나는지",
    "confidence": 0.95 } ] }
```

`type` 은 `setting` / `character` / `timeline` / `space` / `event` / `foreshadow` 중 하나.

> **`/extract` 와 결정적으로 다르다.** `/extract` 는 몸통이 알아서 변환해 주지만
> `/review` 는 `ReviewOutput.model_validate()` 로 곧바로 검증한다.
> 필드 하나만 어긋나도 거기서 터지고 회차가 `failed` 로 떨어진다.

### 보조 엔드포인트

| | 하는 일 | 비용 |
|---|---|---|
| `GET /health` | 서버가 살아 있는지 + 현재 모드 | 없음 |
| `GET /health/llm` | Claude 통로가 뚫려 있는지 (`max_tokens=1`) | 사실상 0 |

## 4. 모드 — `echo` 와 `llm`

`.env` 에서 엔드포인트별로 따로 켠다.

> ⚠️ **주의 — echo 가 기본값이다 (`.env.example`).** echo 모드는 **원고와 무관하게** 항상 같은
> 샘플(`server/sample_visual.json`, 헤일트라움 이야기)을 돌려준다. 화면에는 인물·사건이 그럴듯하게
> 채워지지만 **실제 분석 결과가 아니다** — 모든 회차가 같은 추출 결과가 된다. 실데이터를 보려면
> `EXTRACT_MODE=llm`, `REVIEW_MODE=llm` 으로 띄우고, 지금 어느 모드인지는 `GET /health` 로 확인한다.

| | `echo` | `llm` |
|---|---|---|
| `/extract` | `server/sample_visual.json` 반환 | Claude 로 1차 추출 |
| `/review` | 원문 앞부분을 문 더미 모순 1건 | Claude 로 2차 검수 |

### `echo` 는 임시 구현이 아니다

배선을 먼저 깔기 위한 발판이었지만, **상시 유지한다.**

- **원인 격리** — 분석이 깨졌을 때 `echo` 로 돌려서 되면 LLM 문제, 안 되면 배선 문제
- **키 없는 개발** — 프론트 담당자가 API 키 없이 전 구간을 돌릴 수 있다
- **비용** — 시각화 UI 를 고칠 때마다 Claude 를 부를 이유가 없다
- **테스트** — 응답이 결정적이라 자동 테스트를 붙일 수 있다

> 몸통의 `PIPELINE_MODE=fake` 와 혼동하지 말 것.
> `fake` 는 HTTP 를 타지 않아 **"몸통 로직이 맞나"** 를 보고,
> `echo` 는 **"몸통↔AI 배선이 맞나"** 를 본다. 격리하는 계층이 다르다.

## 5. 파일 구성

```
C:\glitch_ai\
  server/
    main.py             182줄  FastAPI 앱, 4개 엔드포인트, span_of()
    schemas.py           86줄  몸통 interface.py 미러 — 계약
    llm.py              143줄  Claude 호출. llm 모드에서만 import 된다
    sample_visual.json   21KB  echo 모드 응답. 몸통 fake_visual.json 과 동일
  prompt/
    analysis_prompt.txt  98줄  1차 추출 (weave yujin 브랜치에서 가져옴)
    review_prompt.txt    97줄  2차 검수 (이 프로젝트에서 작성)
  check_contract.py      86줄  배선 검증 — 몸통 RemotePipeline 으로 호출
  check_review.py       109줄  검수 품질 시나리오 — 모순 2건/함정 2건
  sample_chapter.txt           테스트용 원문 (하늘도시 아르카)
  run.bat  requirements.txt  .env  .env.example  README.md
```

### 설계 결정 두 가지

**오프셋은 서버가 계산한다.** LLM 에게 `start`/`end` 를 세라고 시키면 거의 틀린다.
프롬프트에서는 `quote` 만 받고 `main.py` 의 `span_of()` 가 `chapter_text.find()` 로
위치를 찾는다. 못 찾으면 `0,0` 으로 두고 경고만 남긴다 — 하이라이트를 못 그릴 뿐
분석은 살린다.

**stateless.** 이 서버는 DB 도 파일도 쓰지 않는다. 원문·결과·캐논 저장은 전부 몸통이
한다. 진실 원천이 둘로 갈라지면 재분석·수정·회차 삭제에서 어긋나기 때문이다.
(원본 `Project_scope_AI` 의 `embed_events.py` 는 파일 기반 배치 구조였는데,
서버로 옮기며 요청→메모리→응답으로 바꿨다.)

## 6. 검수 프롬프트에서 신경 쓴 것

`prompt/review_prompt.txt` 는 분량의 절반을 **오탐 방지**에 썼다.
작가는 잘못된 지적이 몇 건만 섞여도 기능 전체를 신뢰하지 않게 된다.

"모순이 아닌 것"으로 명시한 항목:

- 인물의 성장·변심·각성 — 서사의 본질이다
- 인물의 거짓말·오해 — 인물이 틀린 말을 하는 건 설정 오류가 아니다
- 아직 안 밝혀진 사정 — 복선과 반전은 나중에 회수된다
- 새 정보의 추가 — 확장이지 충돌이 아니다. 기존 항목과 **정면으로** 어긋날 때만 모순
- 회상·꿈·시점 이동
- `confidence` 0.5 미만은 아예 보고 금지

기존 캐논이 비어 있으면(1화) 무조건 빈 배열을 낸다.

## 7. 현재 상태

| | |
|---|---|
| `EXTRACT_MODE` | `llm` — 실제 Claude (`claude-haiku-4-5`) |
| `REVIEW_MODE` | `llm` |
| 서버 | **정지 상태** (`run.bat` 으로 기동) |
| 몸통 | `PIPELINE_MODE=remote`, `QUEUE_MODE=inline` |

### 검증된 것 / 안 된 것

| 구간 | 상태 |
|---|---|
| 몸통 파이프라인 레이어 ↔ AI 서버 | **검증 완료** |
| 프론트 → 몸통 API → 큐 → 파이프라인 | 미확인 (DB 는 준비됨, 아직 안 태워봤다) |

`check_contract.py` 는 몸통의 `RemotePipeline` 을 그대로 import 해서 호출한다.
운영에서 `get_pipeline()` 이 돌려주는 것과 같은 객체이므로, 파이프라인 경계는
진짜로 검증된 것이다. 그 위쪽(라우터·큐·DB·캐논 병합)은 아직 안 태워봤다.

**1차 추출 (실제 Claude, 242자 원문):**

```
canon_delta: worldview=3 characters=3 relations=5 timeline=3 spaces=5 events=2
entity_key : RULE_001, CHAR_001, CHAR_001->CHAR_002 …  (해시 폴백 아님)
```

**2차 검수 (심어둔 모순 2건 / 함정 2건):**

```
[정상] type=setting   conf=0.95  "연우는 스물세 번째 생일 아침에도 아무렇지 않게 지상을…"
[정상] type=character conf=0.98  "집에 들어서자 어머니 서린이 부엌에서 아침을 차리고 있었다."
함정(하람의 성장 / 새 구역 정보) 2건 → 걸리지 않음
캐논 빈 상태 → 0건
```

> 시나리오 테스트는 **1회만** 돌렸다. 재현성은 확인하지 않았다.

## 8. 알려진 이슈

**타임아웃.** 몸통 `remote.py` 는 120초 제한인데 **242자 원문에 26초** 걸렸다.
실제 회차는 수천 자이고 출력 토큰(`max_tokens=8192`)이 지연을 지배하므로 넘칠 수 있다.
넘기면 `httpx.ReadTimeout` 으로 회차가 `failed` 가 된다.
→ 실제 회차 길이로 재보고 필요하면 `timeout=300` 으로 올린다.

**`JsonNormalization` 미구현.** 원본 `Project_scope_AI` 의 `char_resolver.py`,
`split_idmanager.py` 가 빈 파일이다(동일인물 병합·ID 관리).
지금은 몸통이 `character_id` 로 `entity_key` 를 만들어 줘서 없어도 돈다.
회차가 쌓여 "연우"와 "그 청년"이 다른 인물로 잡히기 시작하면 그때 필요하다.

**ERS 미적용.** 현재 `/review` 는 캐논을 통째로 프롬프트에 넣는다.
캐논이 커지면 BGE-M3 Top-K 로 관련 항목만 추려야 한다.
`requirements.txt` 에 의존성이 주석 처리돼 있고, `run_review()` 만 고치면 된다.
**지금은 넣지 말 것** — 2GB 모델이라 기동만 느려진다.

**Git Bash 인코딩.** `curl -d '{...한글...}'` 은 인코딩이 깨져 400 이 난다.
서버 문제가 아니다. JSON 을 파일로 만들어 `--data-binary @file` 을 쓴다.

## 9. 남은 일

1. **[완료 2026-10-12]** 프론트 실데이터 경로. 시각화 탭은 회차를 고르면 몸통의
   `GET /chapters/{no}/visual`(이 서버 `/extract` 의 rich JSON 원본), "전체"면 `GET /canon?view=...`
   (저장된 캐논 6뷰)로 그린다. 하드코딩 데모는 없다. 프론트는 이 서버를 직접 부르지 않는다.
2. **전체 스택 관통** — 실제 회차 업로드 (회차당 API 2회). DB 는 준비됐다(부록 A)
3. **타임아웃 실측** — 2번 하면서 자연히 측정된다
4. **검수 품질 다듬기** — 실제 원고에서 오탐이 나오면 `review_prompt.txt` 의
   "모순이 아닌 것" 목록에 추가한다
5. **ERS 삽입** — 캐논이 커진 뒤에
6. **`JsonNormalization`** — 동일인물 문제가 실제로 생긴 뒤에

## 10. 다시 켤 때 주의

몸통 `.env` 가 `PIPELINE_MODE=remote` 다. **AI 서버가 꺼진 채로 몸통에서 분석을
돌리면 connection refused 로 회차가 `failed` 가 된다.** 둘 중 하나를 한다.

- `C:\glitch_ai\run.bat` 으로 AI 서버를 켠다
- 몸통 `.env` 를 `PIPELINE_MODE=fake` 로 되돌린다 (원본: `.env.bak.fake`)

비용 없이 개발하려면 `C:\glitch_ai\.env` 에서 `EXTRACT_MODE=echo`,
`REVIEW_MODE=echo` 로 두고 서버만 켠다.

---

## 부록 A. 백엔드 DB — AI 서버와는 무관하다

**이 AI 서버는 DB 가 필요 없다.** 의존성에 DB 드라이버가 없고
(`fastapi` `uvicorn` `pydantic` `anthropic` `python-dotenv` 뿐),
코드에 `psycopg`/`sqlalchemy`/`postgres` 가 한 번도 나오지 않는다.
stateless 원칙 그대로다.

PostgreSQL 이 필요한 것은 **몸통(`C:\glitch_integrated`)뿐이다.**
헷갈리기 쉬운 지점이라 여기 정리해 둔다.

### 현재 구성 (2026-08-30 기준)

| | |
|---|---|
| DB | **로컬 PostgreSQL 16 서비스, 포트 5432** |
| 데이터베이스명 | `glitch_integrated` (계정 `glitch` / `glitch`) |
| 마이그레이션 | `0003_visual_json` (head) |
| Docker | **쓰지 않음** — `glitch-db` / `glitch-redis` 컨테이너는 생성된 적 없다 |
| 큐 | `QUEUE_MODE=inline` — Redis 불필요 |

`docker-compose.yml` 은 DB 를 5433 에 매핑하도록 쓰여 있다(로컬 PG 가 5432 를
쓰고 있어 회피한 것). 그래서 **`.env` 의 포트만 보면 어느 방식인지 알 수 있다.**

```
5432 → 로컬 PostgreSQL 서비스   (현재)
5433 → docker 컨테이너
```

### 다른 PC 로 옮길 때 — docker 로 바꾸는 법

코드는 건드리지 않는다. `.env` 두 줄과 명령 두 개뿐이다.

```bash
docker compose -f docker-compose.yml up -d db
```

```
DATABASE_URL=postgresql+asyncpg://glitch:glitch@localhost:5433/glitch_integrated
DATABASE_URL_SYNC=postgresql+psycopg2://glitch:glitch@localhost:5433/glitch_integrated
```

```bash
.venv\Scripts\python.exe -m alembic upgrade head
```

다른 PC 에는 PostgreSQL 16 이 깔려 있을 보장이 없으므로 **그쪽에서는 docker 가 정답이다.**

### 데이터는 따라가지 않는다

컨테이너는 빈 DB 로 시작한다. `alembic upgrade head` 는 **스키마만** 만든다.
기존 데이터를 가져가려면 덤프를 옮긴다.

```bash
# 이 PC 에서 뽑기
"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" ^
  -h localhost -p 5432 -U glitch -Fc -f glitch.dump glitch_integrated

# 다른 PC 의 docker DB 로 넣기 (up -d db 이후)
"C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" ^
  -h localhost -p 5433 -U glitch -d glitch_integrated --clean --if-exists glitch.dump
```

`pg_restore` 가 `alembic_version` 테이블까지 통째로 가져가므로 복원 후
`alembic upgrade head` 를 따로 돌릴 필요가 없다.

> 다른 PC 에 PostgreSQL 클라이언트가 없으면 컨테이너 안의 것을 쓴다:
> `docker exec -i glitch-db pg_restore -U glitch -d glitch_integrated --clean --if-exists < glitch.dump`

### AI 서버를 옮길 때

DB 를 모르므로 신경 쓸 것이 거의 없다. 폴더를 복사하고 `.venv` 를 다시 만든 뒤
`run.bat` 을 돌리면 된다. **챙길 것은 `.env` 의 `ANTHROPIC_API_KEY` 하나뿐이다**
(`.gitignore` 에 걸려 있어 저장소로는 따라가지 않는다).
