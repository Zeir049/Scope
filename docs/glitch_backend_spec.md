> **상태값·API 계약은 [`glitch_api_contract.md`](glitch_api_contract.md)가 최신이다.** 이 명세의 상태 머신(`analyzing` 등)·`analyze` 단일 단계 설명은 2026-08 이전 기준이며, 전체 그림은 [`ARCHITECTURE.md`](ARCHITECTURE.md).

# Glitch 백엔드 명세 (Claude Code 핸드오프용)

> **Glitch** — 장편 서사(소설)의 세계관·설정 규칙 기반 모순("균열")을 잡아주는 AI 탐지 시스템.
> 피그마 프로토타입 화면을 분석해, **백엔드 몸통(게이트웨이)** 구현에 필요한
> 화면별 API·DB 매핑과 데이터 흐름을 정리한 문서.
>
> **스택**: Python + FastAPI · PostgreSQL · LLM 파이프라인은 인터페이스 뒤로 분리
> **이 문서의 범위**: 인증 / 프로젝트·회차 관리 / 원문 업로드 / 파이프라인 호출 / 결과 저장
> **범위 밖**: 모순 검출 LLM 파이프라인 내부 로직 (별도 영역)

---

## 0. 가장 중요한 발견 — "회차 누적 + 캐논 대조" 모델

원문 업로드 화면의 문구가 이 시스템의 본질을 보여줍니다.

> "1~3화는 저장되어 있습니다. 이번에 새 원고인 4화를 업로드해 기존 서사와 대조합니다."
> 작품: 금도끼 은도끼 · 업로드 대상: 4화 · 작가: Cho
> 상태칩: [1화 저장됨] [2화 저장됨] [3화 저장됨] [4화 신규]

핵심은 단발 분석이 아니라 **누적 대조**입니다.

- 하나의 **프로젝트(작품)** 는 여러 **회차(chapter)** 로 구성됨
- 저장된 회차들로부터 작품의 **"캐논(canon)"** — 세계관·인물·시간·공간·사건·복선 구조 — 이 누적됨
- 새 회차를 업로드하면 → 파이프라인이 **신규 회차 vs 기존 캐논**을 대조 → 모순 검출
- 사용자가 결과에 만족하면 → 그 회차를 **저장(commit)** → 회차 본문 + 분석 결과가 캐논에 병합됨

**몸통 설계에 주는 함의**: 단순 "텍스트 1개 분석"이 아니라, 프로젝트별로 누적되는 **상태(캐논)** 를 관리해야 합니다. 이게 데이터 흐름의 중심축입니다.

---

## 1. 몸통(백엔드)의 책임 범위

```
사용자 ──① 인증──▶ ┌──────────────────────────────────┐
                    │            백엔드 몸통              │
사용자 ──② 회차 업로드─▶│  - 인증/세션                       │
                    │  - 프로젝트·회차 CRUD              │      ┌─────────────┐
                    │  - 원문(회차 텍스트) 저장          │──③──▶│  LLM 파이프라인 │
사용자 ◀─⑤ 결과 반환──│  - 파이프라인 인터페이스 호출 ─────┼──④──│  (인터페이스    │
                    │  - 결과 임시 보관 / 캐논 병합       │◀────│   뒤로 분리)    │
사용자 ──⑥ 저장하기──▶│  - 저장(commit) 처리              │      └─────────────┘
                    └──────────────────────────────────┘
                                  │
                                  ▼
                            PostgreSQL
```

몸통이 하는 일 (4가지 + 캐논 관리):
1. **인증** — 회원가입 / 로그인 / 비밀번호 찾기 / 로그아웃 / 세션(JWT)
2. **프로젝트·회차 관리** — 작품 생성·조회·삭제, 회차 업로드·목록·상태
3. **파이프라인 중개** — 회차 텍스트 + 기존 캐논을 인터페이스에 넘기고 결과를 받음
4. **결과 저장** — 사용자가 만족한 결과를 영속화하고 캐논에 병합

몸통이 **하지 않는** 일: 청킹, 클레임 추출, 임베딩, 모순 판정 LLM 호출 (= 파이프라인 영역).

---

## 2. 화면별 명세 (화면 → API → DB)

각 화면에서 어떤 버튼이 어떤 API를 부르고 어떤 테이블이 바뀌는지 매핑합니다.

### 2.1 서비스 진입 (랜딩)
- 화면: Glitch 로고 + "장편 서사의 세계관, 규칙 기반 모순을 찾아드립니다" + **[시작하기]** 버튼, 상단 네비(Main/Project/About/Service)
- 동작: [시작하기] → 로그인 화면으로 이동 (정적, API 없음)
- 백엔드: 없음 (프론트 라우팅)

### 2.2 로그인
- 화면: Email / Password 입력, **[Sign In]**, "Forgot password?", 하단 "계정이 없으신가요? **회원가입**"
- API:
  - `POST /auth/login` — body `{ email, password }` → `{ access_token, user }`
  - [회원가입] 링크 → 회원가입 화면
  - [Forgot password?] → `POST /auth/forgot-password` `{ email }` → 재설정 메일 발송
- DB: `users` 조회, 비밀번호 해시 검증

### 2.3 회원가입
- 화면: 회원가입 폼 (이메일/비밀번호 등 — 폼 필드는 프론트 확정 필요)
- API: `POST /auth/register` — body `{ email, password, name }` → 계정 생성 후 자동 로그인 또는 로그인 화면 이동
- DB: `users` INSERT (이메일 유니크 제약, 비밀번호 해시 저장)

### 2.4 내 드라이브 (개인 드라이브)
- 화면: "내 드라이브" 제목, **[새 프로젝트 만들기]**(폴더+ 아이콘), 우측 검색창, 프로젝트 카드 그리드(제목/썸네일/Title/Description), 카드별 **🗑 삭제** 아이콘, 하단 페이지네이션(1·2·3…67·68)
- API:
  - `GET /projects?page={n}&q={검색어}` → `{ items: [...], page, total_pages }` (페이지네이션 + 검색)
  - 카드 클릭 → `GET /projects/{id}` → 워크스페이스로 이동
  - [새 프로젝트 만들기] → 프로젝트 생성 팝업
  - [🗑] → `DELETE /projects/{id}`
- DB: `projects` SELECT(소유자 필터 + 검색 + LIMIT/OFFSET), DELETE

### 2.5 새로운 프로젝트 생성 (팝업)
- 화면: 좌측 카드 "**새로운 프로젝트 생성**" + `프로젝트명 입력` 필드 + **[생성 및 시작]**, 우측 카드 "User: Cho Euna" + **로그아웃 아이콘**
- API:
  - `POST /projects` — body `{ name }` → `{ project_id }` → 생성 후 워크스페이스로 이동
  - 로그아웃 아이콘 → `POST /auth/logout` (또는 클라이언트 토큰 폐기)
- DB: `projects` INSERT (owner=현재 사용자)

### 2.6 원문 업로드  ★핵심 입력 화면
- 화면: 우측 상단 토글 **[원문입력] / [자료정리]**, "원문 업로드" 제목, 안내문("1~3화는 저장되어 있습니다. 이번에 새 원고인 4화를 업로드해 기존 서사와 대조합니다"), **드래그&드롭 업로드 영역**, 메타 카드 3개(**작품**: 금도끼 은도끼 / **업로드 대상**: 4화 / **작가**: Cho), 회차 상태칩([1화 저장됨][2화 저장됨][3화 저장됨][**4화 신규**])
- API:
  - `GET /projects/{id}/chapters` → 회차 목록 + 각 상태(saved/draft/new) → 상태칩 렌더링
  - `POST /projects/{id}/chapters` — multipart 파일 또는 `{ chapter_no, title, text }` → 신규 회차 생성(status=uploaded)
  - **[분석 실행]** (업로드 후) → `POST /projects/{id}/chapters/{cno}/analyze` → 파이프라인에 **회차 텍스트 + 기존 캐논**을 넘기고 분석 시작
- DB: `chapters` INSERT/SELECT, 분석 job 등록
- 데이터 흐름: 이 화면이 0장의 "신규 회차 vs 캐논 대조"를 트리거하는 지점

### 2.7 워크스페이스 — 원문입력 뷰 (모순 하이라이트)
- 화면: 좌측 사이드바(Search / + New Chats / Chats 목록: Project_1, Simple Design System… / 하단 사용자 프로필 "조은아 Pro" + ⚙ 설정), 중앙 본문 에디터(상단 탭: 세계관·인물·시간·공간·사건·복선), 본문에 **빨간색 하이라이트 = 검출된 모순 구간**, 우측 상단 **[원문입력]/[자료정리]** 토글, 하단 입력바 + 전송 버튼, 우측 **[저장하기]**
- ⚙ 설정 드롭다운: 계정 / 내 공간들 / 구독 / 로그아웃
- API:
  - `GET /projects/{id}/chapters/{cno}/result` → `{ status, highlighted_text, contradictions[] }`
    - status 가 분석중이면 진행상황 폴링 (3장 상태머신)
  - 하이라이트 클릭 → 해당 모순 상세(근거·충돌 대상 회차/구간)
  - 좌측 채팅/프로젝트 목록 → `GET /projects`
  - ⚙ 계정/구독 → 계정·구독 화면 API (구독은 선택 범위)
- DB: `analysis_results`, `contradictions` SELECT

### 2.8 워크스페이스 — 자료정리 뷰 (캐논 6탭)
"자료정리" 토글 시 보이는, 누적된 캐논의 구조화 뷰. 탭별로 데이터 형태가 다릅니다.

| 탭 | 화면 내용 | 데이터 형태 | 저장 테이블(예시) |
|----|----------|------------|------------------|
| **세계관** | 작품 설정 규칙 리스트 + 설명 텍스트 | 항목 리스트(텍스트) | `canon_worldview` |
| **인물** | 인물관계도 (노드=인물, 화살표=관계, 그룹: 회장/부회장/노동자/청탁…) | 그래프(노드+엣지+그룹) | `canon_characters`, `canon_relations` |
| **시간** | 타임라인 축 위 장면(S#1…) 배치 | 시간순 이벤트 | `canon_timeline` |
| **공간** | 장면별 공간/지도 배치 | 공간-장면 매핑 | `canon_spaces` |
| **사건** | 사건 리스트 + 서사 구조 타임라인(암시적 사건→첫 번째 궁지→두 번째 궁지→절정) | 사건 시퀀스 | `canon_events` |
| **복선** | 복선 트리(설치→회수 계층 구조) | 트리(부모-자식) | `canon_foreshadowing` |

- API: `GET /projects/{id}/canon?view={worldview|characters|timeline|spaces|events|foreshadowing}` → 탭별 구조화 JSON
- DB: 위 canon_* 테이블 SELECT
- 참고: 이 구조화 데이터는 **파이프라인이 생성**하고, 몸통은 **저장·조회·병합**만 담당.

### 2.9 결과 저장 & 경고창
- 화면: **[저장하기]** 버튼 → 현재 회차 분석 결과를 캐논에 반영(commit). "자료보기 → 자료정리 이동 / 검토하기 → 경고창" 플로우 = 저장 안 된 상태에서 다른 화면으로 이동 시 **경고 팝업**.
- API:
  - `POST /projects/{id}/chapters/{cno}/save` → 해당 회차 status=saved 로 전환 + 분석 결과를 canon_* 테이블에 병합
  - 미저장 이동 경고는 프론트 처리(서버는 draft/saved 상태만 제공)
- DB: `chapters.status` UPDATE, `analysis_results` → canon_* MERGE, 트랜잭션으로 원자적 처리

---

## 3. 회차 상태 머신 (데이터 관리의 뼈대)

`chapters.status` 를 단일 진실 원천으로 둡니다.

```
uploaded  →  analyzing  →  reviewed  →  saved
(업로드됨)    (대조 분석중)   (결과 확인,    (캐논 병합 완료)
                            저장 전 draft)
   │            │             │
   └────────────┴─────────────┴──→ failed (분석 실패)
```

- `uploaded`: 신규 회차 텍스트만 저장된 상태("4화 신규" 칩)
- `analyzing`: 파이프라인이 캐논과 대조 중 → 프론트는 폴링으로 진행률 표시
- `reviewed`: 결과(하이라이트·모순)는 나왔으나 아직 저장 안 됨 → 이 상태에서 이동하면 경고창
- `saved`: 사용자가 [저장하기] → 캐논 병합 완료("N화 저장됨" 칩)

**원칙**: 캐논 병합은 `saved` 전환 시 **딱 한 번**, 트랜잭션 안에서. 같은 회차 중복 저장 방지(멱등).

---

## 4. DB 스키마 (PostgreSQL)

```
users
  id            uuid  PK
  email         text  UNIQUE NOT NULL
  password_hash text  NOT NULL
  name          text
  plan          text  DEFAULT 'free'   -- 'free' | 'pro' (구독)
  created_at    timestamptz

projects                              -- 작품
  id            uuid  PK
  owner_id      uuid  FK → users
  name          text  NOT NULL        -- 프로젝트명 / 작품명
  author        text                  -- 작가 표기
  thumbnail_url text
  description   text
  created_at    timestamptz
  updated_at    timestamptz

chapters                              -- 회차 (작품의 각 화)
  id            uuid  PK
  project_id    uuid  FK → projects
  chapter_no    int   NOT NULL        -- 1화, 2화 …
  title         text
  raw_text      text                  -- 업로드된 원문
  raw_path      text                  -- 파일 업로드 시 저장 경로
  status        text  NOT NULL        -- 3장 상태머신
  created_at    timestamptz
  UNIQUE (project_id, chapter_no)

analysis_results                      -- 회차별 분석 결과(저장 전/후 모두 보관)
  id            uuid  PK
  chapter_id    uuid  FK → chapters
  highlighted   jsonb                 -- 본문 + 모순 하이라이트 구간
  raw_output    jsonb                 -- 파이프라인 원본 응답(감사/재현용)
  created_at    timestamptz

contradictions                        -- 검출된 모순 (사용자 표시용)
  id            uuid  PK
  chapter_id    uuid  FK → chapters
  span          jsonb                 -- 신규 회차 내 위치(하이라이트)
  conflict_ref  jsonb                 -- 충돌한 기존 캐논/회차 위치
  type          text                  -- 'setting'|'character'|'timeline'|'space'|'event'|'foreshadow'
  explanation   text                  -- 사용자에게 보여줄 근거
  confidence    real

-- 캐논(누적 구조화 데이터) : 파이프라인이 생성, 몸통은 저장/병합/조회 --
-- ★ 버전 보관(append-only) 방식: 덮어쓰지 않고 이력을 남긴다 --
-- 모든 canon_* 테이블은 아래 공통 버전 컬럼을 가진다:
--   source_chapter   int      -- 이 값이 들어온/변경된 회차
--   version          int      -- 같은 항목의 몇 번째 버전인가 (1,2,3…)
--   is_current       boolean  -- 현재 유효한 버전인가
--   superseded_by    uuid     -- 이 버전을 대체한 새 버전의 id (없으면 NULL)
--   superseded_at_chapter int -- 몇 화에서 대체되었나
--   entity_key       text     -- "같은 항목"을 잇는 논리 키(예: 인물명, 설정 식별자)

canon_worldview     (id, project_id FK, entity_key, item text, detail text, +공통 버전 컬럼)
canon_characters    (id, project_id FK, entity_key, name text, group_name text, attrs jsonb, +공통 버전 컬럼)
canon_relations     (id, project_id FK, entity_key, from_char uuid, to_char uuid, relation text, +공통 버전 컬럼)
canon_timeline      (id, project_id FK, entity_key, scene_label text, order_index int, time_value text, +공통 버전 컬럼)
canon_spaces        (id, project_id FK, entity_key, scene_label text, place text, attrs jsonb, +공통 버전 컬럼)
canon_events        (id, project_id FK, entity_key, label text, stage text, order_index int, +공통 버전 컬럼)
                                          -- stage: '암시'|'궁지1'|'궁지2'|'절정' …
canon_foreshadowing (id, project_id FK, entity_key, label text, parent_id uuid, kind text, +공통 버전 컬럼)
                                          -- kind: 'setup'(설치) | 'payoff'(회수)
```

**버전 보관 방식의 동작** (덮어쓰기 안 함):
- 새 회차가 기존 설정을 바꾸면 → 옛 행을 **삭제하지 않고** `is_current=false`, `superseded_by`=새 행 id, `superseded_at_chapter`=현재 회차로 표시하고, **새 행을 version+1, is_current=true 로 INSERT**.
- 현재 캐논 조회는 `WHERE is_current = true`, 특정 회차 시점 캐논은 `WHERE source_chapter <= N AND (superseded_at_chapter IS NULL OR superseded_at_chapter > N)`.
- `entity_key`로 같은 항목의 버전들을 한 줄기로 묶어, "이 설정이 1화엔 X였는데 4화에서 Y로 바뀜" 같은 **설정 변천사**를 그대로 보여줄 수 있습니다.
- 장점: 어떤 회차로 되돌려도 그 시점 캐논을 재구성 가능(타임머신), 모순 근거를 버전 단위로 정확히 지목, 데이터 손실 없음.

---

## 5. API 전체 목록

```
# 인증
POST   /auth/register
POST   /auth/login
POST   /auth/logout
POST   /auth/forgot-password

# 프로젝트(작품)
GET    /projects?page=&q=          # 내 드라이브: 페이지네이션 + 검색
POST   /projects                   # 새 프로젝트 생성
GET    /projects/{id}              # 워크스페이스 진입
DELETE /projects/{id}              # 카드 삭제

# 회차
GET    /projects/{id}/chapters                      # 회차 목록 + 상태칩
POST   /projects/{id}/chapters                      # 신규 회차 업로드(파일/텍스트)
POST   /projects/{id}/chapters/{cno}/analyze        # 캐논 대조 분석 실행(→파이프라인)
GET    /projects/{id}/chapters/{cno}/result         # 분석 결과/진행상황(폴링)
POST   /projects/{id}/chapters/{cno}/save           # [저장하기] → 캐논 병합

# 캐논(자료정리 6탭)
GET    /projects/{id}/canon?view=worldview|characters|timeline|spaces|events|foreshadowing

# 계정/구독 (선택 범위)
GET    /me
GET    /me/subscription
```

---

## 6. 파이프라인 인터페이스 (몸통 ↔ LLM 분리 지점)

유지보수 핵심. 몸통은 이 추상 인터페이스에만 의존하고, 실제 구현(외부 서버 호출 / 같은 프로세스)은 설정으로 주입.

```python
from typing import Protocol

class AnalysisPipeline(Protocol):
    async def analyze_chapter(
        self,
        chapter_text: str,
        canon: CanonSnapshot,      # 기존 저장 회차들로부터 만든 캐논 상태
    ) -> AnalysisOutput:
        """신규 회차를 기존 캐논과 대조해 모순 + 갱신된 구조화 데이터 반환"""
        ...

# AnalysisOutput (파이프라인 → 몸통 계약)
#   highlighted_text : 본문 + 모순 구간 마킹
#   contradictions   : [{ span, conflict_ref, type, explanation, confidence }]
#   canon_delta      : 이 회차가 캐논에 추가/변경하는 내용
#                      (worldview/characters/relations/timeline/spaces/events/foreshadowing)

# 구현 A — 외부 LLM 서버에 붙이기
class RemotePipeline:   # httpx 로 파이프라인 서버 호출
    ...

# 구현 B — 몸통에 직접 붙이기
class LocalPipeline:    # 같은 프로세스에서 실행
    ...

# 구현 C — 개발용 가짜
class FakePipeline:     # 고정 결과 반환 → 몸통부터 완성 가능
    ...
```

설정 `PIPELINE_MODE=remote|local|fake` 로 주입. 초기엔 `fake`로 몸통 전체(인증·CRUD·저장·캐논 병합)를 완성하고, 파이프라인은 나중에 갈아끼웁니다.

**계약 요점**: 몸통은 `analyze_chapter(text, canon) → output` 만 알면 됩니다. `canon`을 만들어 넘기는 것(저장된 회차 → CanonSnapshot)과 `canon_delta`를 받아 병합하는 것이 몸통의 일이고, 그 사이의 모순 검출은 전부 파이프라인의 일입니다.

---

## 7. 핵심 데이터 흐름 — 신규 회차 한 편의 일생

```
① POST /projects/{id}/chapters         신규 회차 업로드 (status=uploaded)
        │
② POST .../analyze                     캐논 스냅샷 생성 → 파이프라인 호출
        │                              (status=analyzing)
        │   canon = 저장된 회차들로부터 구성
        │   output = pipeline.analyze_chapter(text, canon)
        │   analysis_results / contradictions 에 저장 (status=reviewed)
        ▼
③ GET .../result                       프론트가 폴링 → 하이라이트+모순 표시
        │
④ (사용자가 결과 확인, 마음에 들면)
        ▼
⑤ POST .../save                        트랜잭션 시작
        │   - chapters.status = saved
        │   - canon_delta 를 canon_* 테이블에 병합
        │   트랜잭션 커밋  → 다음 회차는 이 캐논과 대조됨
```

이 루프가 회차마다 반복되면서 캐논이 누적되고, 작품이 길어질수록 대조 정확도가 올라갑니다.

---

## 8. Claude Code 핸드오프 전 확정 사항

- [ ] 회원가입 폼 필드 (이메일/비번 외 닉네임·약관 동의 등)
- [ ] 원문 업로드 허용 포맷 (txt/docx/직접 입력 — "드래그&드롭" 영역 기준)
- [ ] 회차 번호 부여 방식 (자동 증가 vs 사용자 지정)
- [x] 캐논 병합 정책 — **버전 보관(append-only) 확정.** 덮어쓰지 않고 이력 유지 (4장 참고)
- [ ] 파이프라인 연결 방식 (remote/local) 과 그 입출력 JSON 스키마 합의
- [ ] 구독(Pro) 기능 이번 범위 포함 여부
- [ ] 인증 방식 (JWT 세션 / 리프레시 토큰 / 소셜 로그인 여부)

---

## 부록: 한 줄 요약

> **"작품은 회차의 누적이고, 저장된 회차가 캐논을 만든다. 몸통은 회차를 받아 캐논과 함께 파이프라인에 넘기고, 사용자가 만족하면 그 결과를 캐논에 병합한다."**
> 이 한 문장이 Glitch 백엔드 몸통의 전부입니다.
