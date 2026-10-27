# Glitch API 계약서 (프론트엔드 연동용)

> 프론트엔드 담당자에게 주는 문서. 백엔드 내부(DB·파이프라인)는 몰라도 되고,
> **요청을 어떻게 보내고 / 무엇이 돌아오는지** 만 담았다.
> 실제 최신 스펙은 백엔드 실행 후 `GET /docs` (Swagger) 와 `/openapi.json` 에서 확인.
>
> **2026-10-11 융합 1단계 반영 (추가만, 기존 필드는 그대로):** 프로젝트 목록 `page_size`·회차 집계,
> 이름 자동 생성(`Project_N`), 회차 상세·삭제·종류(`kind`), 중복 업로드 409, 모순 판정 PATCH,
> 캐논 시점 조회(`at_chapter`)와 `entity_key`/`attrs`. 각 절의 🆕 표시를 보면 된다.
>
> **2026-10-11 융합 2단계 반영 (🆕2):** 검수 후 자동 저장(`auto_save`), 저장된 회차 재검수,
> 검수 비교 기준 = 앞 회차(N-1화) 시점 캐논, 진행 중 작업 조회 `GET /jobs/active`,
> 분석 중복 요청 409(`current_status`)와 고착 작업 자동 정리.
>
> **2026-10-11 융합 2단계 후속 (🆕3):** 검수 실패·고착 회차 재검수 허용(`failed` + 추출 결과 있음),
> 캐논에 반영된 회차 삭제 금지, 고착 기준 = max(`ANALYSIS_STALE_MINUTES`, 작업 상한 + 5분),
> "저장 후 수정" 공식 경로, 저장 순서와 검수 대조의 관계.

> **2026-10-13 융합 4단계 (🆕4):** 이미 있던 엔드포인트 중 계약서에 빠져 있던 절을 추가했다(동작 변경 없음) —
> `POST /auth/firebase`, `PATCH /projects/{id}`, `POST /projects/{id}/thumbnail`,
> `GET /projects/{id}/chapters/{no}/visual`, `GET /pipeline/health`.
>
> **2026-10-15 캐논 attrs (🆕5, 추가만):** 캐논이 LLM 추출 정보를 버리지 않는다 — 모든 탭 항목(복선 제외)에
> `attrs`(certainty·source_text·사건 summary/cause/result·관계 sentiment 등), 모든 항목에 `version`·`is_current`·
> `superseded_at_chapter`. 회차 기여 조회 `GET /canon?chapter=N`.
> **시각화는 캐논(`GET /canon`)을 쓴다 — 저장 전엔 회차 상세의 `canon_delta`를.** `/visual`(원본 JSON)은 호환용으로 남겨둔다.

---

## 0. 기본 약속 (모든 API 공통)

- **Base URL**: 개발 `http://localhost:8000`, 배포는 별도 안내 → **프론트에서 `.env`로 빼둘 것**
- **요청/응답 본문**: JSON (`Content-Type: application/json`). 파일 업로드만 `multipart/form-data`
- **인증**: 로그인 후 받은 토큰을 이후 모든 요청 헤더에 첨부
  ```
  Authorization: Bearer <access_token>
  ```
- **날짜·시간**: 전부 ISO 8601 문자열 (`"2026-06-21T14:00:00Z"`)
- **ID**: UUID 문자열
- **인증 필요 여부**: 아래 각 API에 🔓(불필요) / 🔒(토큰 필요) 표시

### 에러 응답 — 형태 통일
모든 에러는 동일한 형태로 온다. 프론트는 이 하나만 처리하면 됨.
```json
{ "detail": "에러 메시지" }
```
- 🆕 분기에 필요한 값이 있으면 `detail` 옆에 **최상위 필드가 더 붙을 수 있다**(예: 중복 업로드 409의 `existing_chapter_no`,
  🆕2 분석 중복 요청 409의 `current_status`).
  `detail`은 항상 사람이 읽는 문자열이므로 기존 처리는 그대로 두면 된다.
| 상태코드 | 의미 | 프론트 처리 예 |
|---------|------|---------------|
| 400 | 잘못된 요청(검증 실패) | 입력값 안내 |
| 401 | 미인증/토큰 만료 | 로그인 화면으로 |
| 403 | 권한 없음(남의 자원) | "접근 권한 없음" |
| 404 | 없는 자원 | "찾을 수 없음" |
| 409 | 충돌(중복 이메일/회차 등) | 안내 메시지 |
| 422 | 본문 형식 오류 | (FastAPI 기본) |
| 500 | 서버 오류 | "잠시 후 다시" |

### 페이지네이션 — 형태 통일
목록 API는 항상 이 형태.
```json
{
  "items": [ /* ... */ ],
  "page": 1,
  "total_pages": 68,
  "total_count": 1357
}
```

---

## 1. 인증 (Auth)

### 회원가입 🔓
`POST /auth/register`
```json
// 요청
{ "email": "user@example.com", "password": "secret123", "name": "조은아" }
```
```json
// 응답 201
{ "access_token": "eyJhbGci...", "user": { "id": "uuid", "email": "user@example.com", "name": "조은아", "plan": "free" } }
```
- 실패: 409 (이미 가입된 이메일)

### 로그인 🔓
`POST /auth/login`
```json
// 요청
{ "email": "user@example.com", "password": "secret123" }
```
```json
// 응답 200
{ "access_token": "eyJhbGci...", "user": { "id": "uuid", "email": "user@example.com", "name": "조은아", "plan": "pro" } }
```
- 실패: 401 (이메일/비번 불일치)
- 프론트: 받은 `access_token`을 저장(쿠키 또는 메모리) → 이후 요청에 첨부

### 🆕4 구글 로그인 토큰 교환 🔓  — "시작하기"
`POST /auth/firebase` (`.env` `ENABLE_FIREBASE_AUTH=true`일 때만 등록)
- **화면:** 시작 화면 "시작하기" → Firebase 팝업(또는 데모 로그인) 직후 `auth/backend-auth.js`가 자동 호출
```json
// 요청 — Firebase ID 토큰
{ "id_token": "eyJhbGciOiJSUzI1NiIs..." }
```
```json
// 응답 200 — 로그인과 같은 형태
{ "access_token": "eyJhbGci...", "user": { "id": "uuid", "email": "user@example.com", "name": "조은아", "plan": "free" } }
```
- 서버가 토큰을 검증한 뒤 **이메일 기준으로 계정을 찾거나 만든다**(새 계정은 비밀번호 로그인 불가, 구글 전용).
- `FIREBASE_MODE=google`(기본): Google 공개키로 서명·`aud`(=`FIREBASE_PROJECT_ID`)·만료를 검증.
- `FIREBASE_MODE=fake`: `fake:<email>[:<name>]` 문자열을 **무검증 통과** — 로컬 데모 전용(`?demo=1`). 공개 URL 금지.
- 실패: 401 (`"유효하지 않은 구글 로그인 토큰입니다."` 등), 422 (`id_token` 누락/빈 문자열)

### 로그아웃 🔒
`POST /auth/logout` → 응답 204 (본문 없음)
- 프론트: 저장한 토큰 폐기

### 비밀번호 찾기 🔓
`POST /auth/forgot-password`
```json
// 요청
{ "email": "user@example.com" }
```
```json
// 응답 200
{ "message": "재설정 메일을 보냈습니다." }
```

### 내 정보 🔒
`GET /me` → 현재 로그인 사용자
```json
// 응답 200
{ "id": "uuid", "email": "user@example.com", "name": "조은아", "plan": "pro" }
```

---

## 2. 프로젝트 (내 드라이브)

### 목록 🔒  — "내 드라이브" 화면
`GET /projects?page=1&page_size=6&q=검색어`
- **화면:** 내 드라이브(카드 6개·페이지네이션, `page_size=6`) · 사이드바 "최근 항목"과 검색(`page_size=20`, `q`)
- 쿼리: `page`(기본 1), 🆕 `page_size`(기본 20, **1~50**, 범위 밖이면 400 — 내 드라이브 화면은 6), `q`(검색어, 선택)
- 정렬: `updated_at` 내림차순. 🆕 회차 업로드·재업로드·삭제·상태 전환(추출/검수/저장/실패)이 일어나면
  서버가 프로젝트 `updated_at`을 갱신하므로, **최근 작업한 프로젝트가 맨 앞**에 온다.
```json
// 응답 200
{
  "items": [
    { "id": "uuid", "name": "금도끼 은도끼", "author": "Cho",
      "thumbnail_url": "https://...", "description": "...",
      "created_at": "2026-06-01T09:00:00Z", "updated_at": "2026-06-20T09:00:00Z",
      "chapter_count": 3, "last_chapter_status": "reviewed" }
  ],
  "page": 1, "total_pages": 2, "total_count": 7
}
```
- 🆕 `chapter_count`: 회차 수. `last_chapter_status`: **가장 큰 회차 번호**의 `status` (회차가 없으면 `null`).
  단건 조회·생성·수정 응답에도 같은 두 필드가 들어간다.

### 생성 🔒  — "새 프로젝트 만들기" / "생성 및 시작"
`POST /projects`
- **화면:** 새 프로젝트 이름 모달 "만들기" (이름을 비우면 `name` 없이 보내 `Project_N`)
```json
// 요청
{ "name": "금도끼 은도끼" }
```
```json
// 응답 201
{ "id": "uuid", "name": "금도끼 은도끼", "author": "Cho", "created_at": "...", "updated_at": "...",
  "chapter_count": 0, "last_chapter_status": null }
```
- 프론트: 응답 `id`로 워크스페이스(`/projects/{id}`)로 이동
- 🆕 `name`을 **빼거나 빈 문자열/공백**으로 보내면 서버가 `Project_N`을 붙인다.
  N = 내 프로젝트 중 이름이 정확히 `Project_<숫자>`인 것의 최대값 + 1 (없으면 1).
  ```json
  // 요청 {}  → 응답 201 { "name": "Project_4", ... }   (기존에 Project_3 이 있을 때)
  ```

### 단건 조회 🔒  — 카드 클릭 → 워크스페이스 진입
`GET /projects/{id}`
- **화면:** 드라이브 카드 ✏️ 열기 · 사이드바 프로젝트 클릭 → 세계관 분석하기
```json
// 응답 200
{ "id": "uuid", "name": "금도끼 은도끼", "author": "Cho", "description": "...",
  "created_at": "...", "updated_at": "..." }
```
- 실패: 403(남의 프로젝트), 404(없음)

### 🆕4 수정 🔒  — 카드 제목 클릭 → 이름 바꾸기
`PATCH /projects/{id}`
- **화면:** 내 드라이브 카드 제목 인라인 편집(Enter/포커스 아웃)
```json
// 요청 — 보낸 필드만 바뀐다(부분 수정)
{ "name": "금도끼 은도끼 (개정)" }
// 선택 필드: "author", "description"
```
```json
// 응답 200 — 단건 조회와 같은 형태(chapter_count·last_chapter_status 포함)
{ "id": "uuid", "name": "금도끼 은도끼 (개정)", "author": "Cho", "updated_at": "...", "chapter_count": 3, "last_chapter_status": "saved" }
```
- `name`은 1자 이상(빈 문자열이면 422). `null`을 보내거나 빼면 그 필드는 그대로.
- 실패: 403(남의 프로젝트), 404(없음), 422(본문 형식)

### 🆕4 썸네일 업로드 🔒
`POST /projects/{id}/thumbnail` — `multipart/form-data`, 필드 `file`(이미지)
- **화면:** 아직 없음(카드 썸네일 자리만 있다)
```json
// 응답 200 — 프로젝트(thumbnail_url 이 채워짐)
{ "id": "uuid", "name": "...", "thumbnail_url": "/uploads/thumbnails/3f2a..._cover.png", "...": "..." }
```
- `thumbnail_url`은 같은 오리진 경로(`STORAGE_MODE=local` → `/uploads/...` 정적 서빙).
- 실패: 400 — Content-Type 이 `image/*`가 아니거나, 실제 바이트가 PNG·JPEG·GIF·WebP 가 아님(매직 바이트 검사),
  또는 `MAX_THUMBNAIL_BYTES`(기본 5MB) 초과(`"파일이 너무 큽니다. 최대 5MB까지…"`). 403, 404

### 삭제 🔒  — 카드 🗑 아이콘
`DELETE /projects/{id}` → 응답 204
- **화면:** 드라이브 카드 🗑️ (confirm 후)

---

## 3. 회차 (Chapter)

### 회차 목록 🔒  — 원문 업로드 화면의 상태칩
`GET /projects/{id}/chapters`
- **화면:** 세계관 분석하기의 회차 필터(상태 배지) · 검수 결과 화면 회차 필터 · 원문보기 "회차 기록"
```json
// 응답 200
{
  "items": [
    { "chapter_no": 1, "title": "1화", "status": "saved", "kind": "narrative",
      "created_at": "2026-10-01T09:00:00Z", "updated_at": "2026-10-01T09:05:00Z" },
    { "chapter_no": 2, "title": "[규칙] 설정집", "status": "saved", "kind": "rules",
      "created_at": "...", "updated_at": "..." },
    { "chapter_no": 3, "title": "3화", "status": "uploaded", "kind": "narrative",
      "created_at": "...", "updated_at": "..." }
  ]
}
```
- 🆕 `kind`(`narrative` 서사 원고 | `rules` 설정·규칙 문서), `updated_at` 추가. 원문은 목록에 없다 → 회차 상세에서.
- `status` 값: `uploaded` | `extracting` | `extracted` | `reviewing` | `reviewed` | `saved` | `failed`
- 프론트: `saved`→"N화 저장됨" 칩, 그 외→진행 상태(추출중/추출됨/검수중 등) 표시

### 회차 업로드 🔒  — 드래그&드롭 또는 텍스트 입력
`POST /projects/{id}/chapters`
- **화면:** 세계관 분석하기 "분석 시작" — 파일은 multipart(`kind=rules|narrative`), 직접 입력은 JSON. 중복 409 → "이미 N화로 올라간 원고예요" 안내
- 방법 A) 파일: `multipart/form-data`, 필드 `file`, `chapter_no`, `title`, 🆕 `kind`
  - 지원 포맷: **`.txt` · `.md` · `.docx` · `.pdf`** (PDF는 텍스트 레이어가 있는 파일만; 스캔 이미지 PDF는 미지원)
  - 미지원 확장자·추출 실패: 400
- 방법 B) 텍스트:
```json
{ "chapter_no": 4, "title": "4화", "text": "원고 본문 전체...", "kind": "narrative" }
```
```json
// 응답 201
{ "chapter_no": 4, "title": "4화", "status": "uploaded", "kind": "narrative",
  "created_at": "...", "updated_at": "..." }
```
- 🆕 `kind`: `narrative`(기본, 생략 가능) | `rules`. 그 외 값은 400.
  (참고: 지금 파이프라인은 아직 제목이 `[규칙]`으로 시작하는지로 규칙 문서를 구분한다. `kind`는 저장·표시용.)
- 실패: 409 (이미 있는 회차 번호)
- 🆕 실패: **409 (같은 프로젝트에 같은 원문이 이미 있음)** — 서버가 파싱된 원문의 sha256으로 판단한다.
  파일/텍스트 어느 방식이든 같다. 응답에 기존 회차 번호가 온다:
  ```json
  // 응답 409
  { "detail": "같은 내용의 원고가 이미 2화로 올라가 있습니다.", "existing_chapter_no": 2 }
  ```
  - 프론트: `existing_chapter_no`가 있으면 "이미 N화로 올라간 원고" 안내 + 그 회차로 이동 버튼.
  - 다른 프로젝트의 같은 원문은 막지 않는다.

### 🆕 회차 재업로드(원고 교체) 🔒
`PUT /projects/{id}/chapters/{chapter_no}`
- 본문은 업로드와 같다(파일 `file`/`title`/`kind` 또는 JSON `{ "title", "text", "kind" }`, 회차 번호는 경로).
- 상태가 `uploaded`로 돌아가고 이전 분석 결과·모순은 지워진다. 응답은 업로드와 같은 형태(200).
- `kind`를 생략하면 **기존 값 유지**. 잘못된 값은 400.
- **중복 원문이어도 거절하지 않는다**(해시만 갱신). 중복 409는 새 업로드(POST)에만 적용된다.

### 🆕 회차 상세 🔒  — 원문 보기 / 실패 사유
`GET /projects/{id}/chapters/{chapter_no}`
- **화면:** 원문보기(`raw_text`) · 1차 탭 실패 안내(`failed_stage`/`failed_detail`)
```json
// 응답 200
{
  "chapter_no": 3,
  "title": "3화",
  "kind": "narrative",
  "status": "failed",
  "raw_text": "원고 본문 전체...",
  "raw_path": "3화.docx",
  "content_hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "created_at": "2026-10-11T09:00:00Z",
  "updated_at": "2026-10-11T09:02:10Z",
  "failed_stage": "extract",
  "failed_detail": "AI 서버 응답 시간 초과",
  "contradiction_count": 0
}
```
- `failed_stage`(`extract`|`review`)·`failed_detail`은 실패 기록이 있을 때만 값이 있고, 아니면 `null`.
- `contradiction_count`: 이 회차의 모순 수(`reviewed`/`saved`에서 의미 있음).
- `raw_path`: 파일로 올린 경우 원래 파일명, 텍스트로 올렸으면 `null`.
- 실패: 403(남의 프로젝트), 404(없는 프로젝트/회차)

### 🆕 회차 삭제 🔒
`DELETE /projects/{id}/chapters/{chapter_no}` → 응답 204
- **`saved` 회차는 삭제 불가 → 409** `{ "detail": "저장된 회차는 삭제할 수 없습니다." }` (캐논에 반영된 회차)
- **분석 진행 중(`extracting`/`reviewing`) → 409** `{ "detail": "분석이 진행 중인 회차는 삭제할 수 없습니다." }`
- 🆕3 **캐논에 반영된 적이 있는 회차 → 409** `{ "detail": "캐논에 반영된 회차는 삭제할 수 없습니다." }`
  상태와 무관하다. 예: 저장했다가 재검수에 실패해 `failed`가 된 회차, 저장 후 편집 중(`extracted`)인 회차.
  (지우면 캐논에 출처 회차가 없는 설정이 남기 때문.)
- 그 외(캐논 기여가 없는 `uploaded`/`extracted`/`reviewed`/`failed`)는 삭제되며 분석 결과·모순도 함께 지워진다.
- 실패: 403(남의 프로젝트), 404(없는 회차)

### 분석은 2단계 — ① 추출 → ② 검수

분석은 **두 번의 사용자 요청**으로 나뉜다.

```
uploaded → [extract] → extracting → extracted → [review] → reviewing → reviewed → (자동 저장) → saved
                                    └ 사용자가 추출 결과 검토                     └ auto_save:false 면 여기서 멈춤 → [save]
saved → [review] → reviewing → reviewed → (자동 저장) → saved        ← 🆕2 재검수
어느 단계든 실패 시 → failed (+ failed_stage)
```

> 🆕2 **분석 중복 요청 409.** `extracting`/`reviewing` 중인 회차에 extract·review·analyze를 또 보내면 409:
> ```json
> // 응답 409
> { "detail": "이미 분석이 진행 중입니다 (현재 상태: extracting).", "current_status": "extracting" }
> ```
> 프론트: `current_status`가 오면 새로 시작하지 말고 기존 작업을 폴링한다.
>
> 🆕2 **고착 작업 자동 정리.** 진행 중 상태로 **고착 기준 시간** 넘게 안 바뀐 회차는 워커가 죽은 것으로 본다.
> 🆕3 고착 기준 = **max(`ANALYSIS_STALE_MINUTES`, `JOB_TIMEOUT_SECONDS`/60 + 5분)** — 기본값이면 **20분**
> (작업 상한 900초 + 5분). 설정을 짧게 잡아도 아직 돌 수 있는 작업을 고착으로 보지 않는다.
> 그 회차에 새 분석 요청이 오면 서버가 먼저 `failed`(`failed_stage` = `extract`|`review`,
> 사유 `"시간 초과로 중단된 작업"`)로 기록하고 요청을 이어서 판단한다.
> - extract·analyze는 그대로 202로 새로 시작된다.
> - 🆕3 review도 **추출 결과가 남아 있으면 202로 바로 재검수**가 시작된다(검수 중 고착은 보통 이 경우).
>   추출 결과가 없을 때만 409 → 다시 extract 부터.
> - 영구히 409에 갇히는 일은 없다. 고착 여부는 `GET /jobs/active`의 `stale`로 미리 볼 수 있다.
> - 🆕3 작업이 작업 상한(`JOB_TIMEOUT_SECONDS`)에 걸려 끊기면 서버가 그 자리에서
>   `failed`(사유 `"작업 시간 초과(arq job_timeout)"`)로 기록한다 — 고착 기준을 기다리지 않는다.

#### ① 1차 추출 🔒  — "원문에서 6기준 추출"
`POST /projects/{id}/chapters/{chapter_no}/extract`
- **화면:** "분석 시작"(업로드 직후) · 1차 탭 "1차 분석 시작"(uploaded) / "다시 분석"(추출 실패)
```json
// 응답 202 (비동기 시작)
{ "chapter_no": 4, "status": "extracting" }
```
- 202 후 result를 **폴링**(예: 2초). `extracted`가 되면 추출 결과(`canon_delta`)를 사용자에게 보여준다.
- 추출은 **지금(최신) 캐논**을 참고 자료로 받는다.

#### ② 2차 검수 🔒  — "기존 서사와 대조" (추출된 회차 · 🆕2 저장된 회차)
`POST /projects/{id}/chapters/{chapter_no}/review`
- **화면:** 1차 탭 "검토하기"(extracted) / "다시 검토하기"(saved) / "다시 분석"(검수 실패) — 바디 없이(auto_save 기본)
```json
// 요청 (🆕2, 바디는 선택 — 없으면 auto_save: true)
{ "auto_save": true }
```
```json
// 응답 202
{ "chapter_no": 4, "status": "reviewing" }
```
- 전제: 회차가 `extracted`, 🆕2 `saved`, 🆕3 `failed`(**추출 결과가 남아 있을 때** — 검수 실패·고착) 중 하나.
  그 외 409. 추출 단계에서 실패한 `failed`는 추출 결과가 없어 409(`"검수할 추출 결과가 없습니다."`). 진행 중이면 409 + `current_status`.
- 🆕2 **`auto_save: true`(기본)** — 검수가 끝나면 서버가 **저장(캐논 병합)까지** 한다.
  폴링하면 `reviewing → reviewed → saved` 순서로 바뀐다(`reviewed`를 건너뛰지 않는다).
  - 폴링 종료 조건은 `reviewed` 또는 `saved`. `reviewed`를 본 직후 `POST /save`를 불러도 안전하다
    (서버가 병합을 한 번만 하고, 이미 저장됐으면 같은 응답을 돌려준다).
- 🆕2 **`auto_save: false`** — 예전처럼 `reviewed`에서 멈춘다. 모순을 확인한 뒤 `POST /save`로 저장.
- 🆕2 **비교 기준 = 앞 회차(N-1화) 시점 캐논.** N화 검수는 1~N-1화까지 저장된 시점의 설정과만 대조한다.
  N화 자신이 넣은 설정과 뒤 회차(N+1화 이후)의 설정은 비교 대상이 아니다. 첫 검수·재검수 모두 같다.
  (1화 검수는 비교할 앞 회차가 없다.)
  🆕3 그래서 **저장 순서가 회차 순서와 어긋나면 대조가 빠진다** — 예: 3화를 먼저 저장하고 2화를 나중에 저장하면,
  3화 검수 때는 2화 설정이 없었고 2화 검수는 3화 설정과 대조하지 않는다. 의도된 동작이다. 회차 순서대로 저장할 것.
- 🆕2 **재검수 (`saved` 회차에 review).** 재업로드·재추출 없이, 저장 때 쓴 추출 결과로 **검수만 다시** 한다.
  - `saved → reviewing → reviewed → saved`(auto_save). 추출 결과가 같으므로 캐논은 바뀌지 않는다.
  - **기존 모순은 전부 지워지고 새 결과로 바뀐다. 작가가 매긴 ✓/✕ 판정(`status`)도 함께 사라진다**(새 모순은 `pending`).
  - 저장 때의 추출 결과가 없는 회차(옛 데이터 등)는 409.
- 🆕3 **검수 실패·고착 회차 재검수 (`failed`에 review).** 추출 결과가 남아 있으면 같은 방식으로 검수만 다시 한다.
  - 기존 모순은 지워진다. 회차 상세의 `failed_stage`/`failed_detail`(마지막 실패 사유)은 재검수가 **성공할 때까지 유지**되고,
    성공하면 비워진다.
  - 저장했던 회차가 재검수 실패로 `failed`가 됐어도 이 방법으로 다시 `saved`까지 갈 수 있다(캐논은 그대로).

#### 🆕3 저장 후 수정 — 공식 경로
저장(`saved`)한 회차의 추출 결과를 고쳐 캐논에 다시 반영하는 전용 API는 없다. 아래 순서로 한다.
```
POST /projects/{id}/chapters/{no}/review   { "auto_save": false }   → 폴링 → reviewed
PATCH/POST/DELETE .../delta/{category}[/{entity_key}]                 → 편집 (상태가 extracted 로 바뀐다)
POST /projects/{id}/chapters/{no}/review   (auto_save 기본 true)      → 폴링 → saved
```
- 편집하면 기존 모순이 낡은 결과가 되므로 서버가 지우고 상태를 `extracted`로 돌린다(아래 "추출 항목 편집" 참고).
  그래서 편집 직후 `POST /save`는 409다 — **review를 한 번 더** 해서 고친 내용 기준으로 모순을 받은 뒤 저장한다
  (`auto_save:false`로 다시 review → `reviewed` → `POST /save` 도 된다).
- 저장 시 캐논은 덮어쓰지 않고 **버전으로** 반영된다: 바뀐 항목은 새 버전(옛 버전은 이력으로 남음),
  이번에 지운 항목은 철회(이 회차가 바꾸기 전 버전이 있으면 그 버전으로 복원), 같은 항목은 그대로.
  `GET /canon?at_chapter=N`으로 시점별 내용을 볼 수 있다.
- 편집 중(`extracted`)에도 이 회차는 캐논에 반영돼 있으므로 삭제는 409.

#### (편의) 한 번에 분석 🔒  — 추출+검수 연속
`POST /projects/{id}/chapters/{chapter_no}/analyze`
```json
// 응답 202
{ "chapter_no": 4, "status": "extracting" }
```
- 추출→검수를 한 번에 실행. 폴링하면 `extracting→extracted→reviewing→reviewed`로 흘러 `reviewed`에서 멈춘다.
  (자동 저장하지 않는다 — 저장은 `POST /save`. 검수 비교 기준은 ②와 같이 N-1화 시점.)
- 진행 중이면 409 + `current_status`.

### 🆕2 진행 중 작업 조회 🔒  — 우측 하단 작업 창 복원
`GET /jobs/active`
- **화면:** 우측 하단 작업 창 — 로그인 직후 복원 + 진행 중 작업이 있는 동안 1.5초 폴링
- 내 프로젝트들에서 **추출/검수 중**(`extracting`|`reviewing`)인 회차 목록. 새로고침·다른 기기에서도 진행 상황을 복원할 때 쓴다.
- 서버는 따로 작업 기록을 두지 않고 회차 `status`에서 바로 만든다. 끝난 작업은 목록에서 사라진다.
```json
// 응답 200
{
  "items": [
    {
      "project_id": "uuid",
      "project_name": "Project_4",
      "chapter_no": 2,
      "title": "2화",
      "status": "extracting",
      "progress": 0,
      "started_at": "2026-10-11T10:02:11Z",
      "stale": false
    }
  ]
}
```
- `started_at`: 회차가 지금 상태(추출 중/검수 중)로 바뀐 시각.
- `progress`: 0~100 (값이 없으면 `null`).
- `stale`: 고착 기준(🆕3 max(`ANALYSIS_STALE_MINUTES`, 작업 상한 + 5분), 기본 20분) 넘게 그대로인 작업 — 워커가 죽었을 가능성. **표시만** 하고 상태는 바꾸지 않는다.
  사용자가 다시 분석을 요청하면 위 "고착 작업 자동 정리" 규칙대로 처리된다.
- 진행 중인 작업이 없으면 `{ "items": [] }`.

### 결과 조회 / 진행상황 폴링 🔒  — 워크스페이스 본문
`GET /projects/{id}/chapters/{chapter_no}/result`
- **화면:** 1차 탭(`canon_delta`) · 2차 탭(`contradictions`) · 작업 창(목록에서 빠진 작업의 최종 상태 확인)
- **상태에 따라 필드가 다르다:**
```json
// 진행중(extracting/reviewing/uploaded) — 200
{ "status": "extracting", "progress": 60 }
```
```json
// 추출 완료(검토 대기) — 200
{
  "status": "extracted",
  "highlighted_text": "...본문...",
  "canon_delta": {
    "worldview": [ { "entity_key": "currency", "item": "화폐 단위는 '냥'", "detail": "...",
                     "attrs": { "certainty": "explicit", "source_text": "..." } } ],
    "characters": [ { "entity_key": "woodcutter", "name": "나무꾼", "group_name": "주요 인물",
                      "attrs": { "description": "...", "aliases": [], "first_appearance_event_id": "EVENT_001",
                                 "traits": [ { "trait": "정직함", "trait_type": "personality", "certainty": "explicit" } ],
                                 "certainty": "explicit", "source_text": "..." } } ],
    "relations": [], "timeline": [], "spaces": [], "events": [], "foreshadowing": []
  }
}
```
- 🆕5 복선을 뺀 모든 항목에 `attrs`(없으면 `null`). 키는 LLM 원본(`/visual`) 이름 그대로이고, 저장하면 캐논 항목의 `attrs`로 그대로 간다 —
  **저장 전 시각화는 이 `canon_delta`로, 저장 후는 `GET /canon?chapter=N`으로** 같은 모양을 그린다.
  | 항목 | `attrs` 키 |
  |---|---|
  | 공통 | `certainty`, `source_text` |
  | characters | `description`, `aliases`, `traits`=[{`trait`,`trait_type`,`certainty`}], `first_appearance_event_id` |
  | relations | `relationship_type`, `sentiment`, `description` |
  | events | `summary`, `cause`, `result`, `main_actor_character_id`, `participant_character_ids` |
  | timeline / spaces | `description` |
  | worldview | (공통만 — 설명은 `detail`) |
```json
// 검수 완료 — 200 (추출 결과 + 모순)
{
  "status": "reviewed",
  "highlighted_text": "...본문...",
  "canon_delta": { "...추출 결과..." : [] },
  "contradictions": [
    {
      "id": "uuid",
      "span": { "start": 1024, "end": 1090, "quote": "주인공은 왼손잡이다" },
      "conflict_ref": { "chapter_no": 2, "quote": "그는 오른손으로 도끼를 던졌다" },
      "type": "character",
      "explanation": "2화에서는 오른손 사용, 4화에서는 왼손잡이로 서술되어 충돌.",
      "confidence": 0.91,
      "status": "pending"
    }
  ]
}
```
- `type` 값: `setting` | `character` | `timeline` | `space` | `event` | `foreshadow`
- 🆕 `status`: 작가의 판정 `pending`(기본) | `confirmed`(✓ 모순 맞음) | `dismissed`(✕ 무시). 아래 "모순 판정" 참고.
- 프론트: `span.start/end`로 본문에 빨간 하이라이트, 클릭 시 `explanation`·`conflict_ref` 표시
- 실패면 `{ "status": "failed", "detail": "...", "failed_stage": "extract" | "review" }`

### 🆕4 회차 시각화 원본 🔒  — ⚠️ 프론트는 더 이상 쓰지 않음(디버그·AI 원본 보존용)
`GET /projects/{id}/chapters/{chapter_no}/visual`
- **화면:** 없음. 🆕5(시각화 V2)부터 시각화 자료 탭은 회차 선택 시에도 캐논(`GET /canon?chapter=N`, 저장 전엔 `result.canon_delta`)만 읽는다.
  이 엔드포인트는 LLM 원본을 확인하는 디버그·AI 담당 대조용으로 남겨 둔다.
```json
// 응답 200 — 파이프라인이 준 rich JSON 원본(LLM prompt_result_1 포맷)
{ "chapter_no": 1,
  "visual": { "worldview_rules": [ { "rule_id": "RULE_001", "content": "...", "description": "...", "source_text": "...", "certainty": "explicit" } ],
              "characters": [ { "character_id": "CHAR_001", "name": "클라인", "aliases": [], "traits": [], "relationships": [], "...": "..." } ],
              "events": [], "times": [], "locations": [] } }
```
```json
// 원본이 없는 회차 — 200 (추출 전, [규칙] 문서, rich JSON 을 주지 않는 파이프라인)
{ "chapter_no": 2, "visual": null }
```
- 1차 추출 때 받은 원본을 그대로 돌려준다. 캐논(`GET /canon`)과 달리 저장 여부·편집과 무관하다.
- 🆕5 **시각화는 이제 캐논을 쓴다** — 저장 전엔 회차 상세(`result`)의 `canon_delta`, 저장 후엔 `GET /canon?chapter=N`.
  이 원본은 편집·재저장을 반영하지 못하므로 화면의 기준이 아니다(호환용으로만 남긴다).
- 복선 항목은 원본 포맷에 없다(복선은 캐논 `view=foreshadowing`).
- 실패: 403(남의 프로젝트), 404(없는 프로젝트/회차)

### 🆕4 분석 서버 사전 점검 🔒
`GET /pipeline/health`
- **화면:** "분석 시작"·"검토하기"·"다시 분석" 누른 직후 "서버 연결 중" 로딩. `ok:false`면 업로드·요청을 보내지 않고 작업 창에 사유
```json
// 응답 200 — 연결됨
{ "ok": true, "mode": "remote", "message": "AI 서버 연결됨" }
```
```json
// 응답 200 — 연결 실패도 200 이다(원인은 message)
{ "ok": false, "mode": "remote", "message": "AI 서버에 연결할 수 없습니다. AI 서버가 켜져 있는지 확인하세요." }
```
- 몸통 → 파이프라인 `health()`만 확인한다. LLM 은 호출하지 않는다(수 초 안에 끝남).
- `mode`: `fake` | `local` | `remote`. 응답 필드는 `ok`·`mode`·`message` 셋뿐이다.
  (2026-10-13까지 있던 `info` — AI 서버 `/health` 응답, llm 모드면 내부 경로 포함 — 는 응답에서 뺐고 서버 로그에만 남긴다.)
- 실패: 401(토큰 없음)

### 🆕 모순 판정 (✓/✕) 🔒
`PATCH /projects/{id}/chapters/{chapter_no}/contradictions/{contradiction_id}`
- **화면:** 2차 탭 ✓(confirmed) / ✕(dismissed), 다시 누르면 pending
```json
// 요청
{ "status": "confirmed" }
```
```json
// 응답 200 — 갱신된 모순 항목 (result 의 contradictions 항목과 같은 형태)
{ "id": "uuid", "span": { "start": 1024, "end": 1090, "quote": "..." },
  "conflict_ref": { "chapter_no": 2, "quote": "..." }, "type": "character",
  "explanation": "...", "confidence": 0.91, "status": "confirmed" }
```
- `status`: `pending` | `confirmed` | `dismissed` (되돌리기는 `pending`). 그 외 값은 400.
- 회차 `status`(진행 상태)는 바뀌지 않는다. `reviewed`·`saved` 어느 쪽에서든 판정할 수 있고 result에 반영된다.
- 실패: 403(남의 프로젝트), 404(없는 회차 / 없는 모순 / **그 회차에 속하지 않은 모순 id**)
- 참고: 재업로드·재추출·`reviewed` 상태 편집으로 모순이 다시 만들어지면 판정도 초기화된다(새 모순은 `pending`).

### 결과 저장 🔒  — "저장하기" 버튼
`POST /projects/{id}/chapters/{chapter_no}/save`
- **화면:** 1차 탭 "저장 재시도" (auto_save 가 실패해 reviewed 에 멈춘 회차만)
```json
// 응답 200
{ "chapter_no": 4, "status": "saved" }
```
- 의미: 이 회차를 캐논에 반영(확정). 이후 회차는 이 내용과 대조됨
- 전제: **`reviewed` 상태에서만 저장 가능**. 추출만 된(`extracted`) 상태로 저장하면 409.
  (캐논 병합은 오직 save 한 곳에서만 일어난다.)
- 프론트: 저장 전(`reviewed`) 상태에서 다른 화면 이동 시 **"저장 안 된 결과가 사라집니다" 경고 팝업** 띄우기 (서버는 status만 제공)
- 🆕2 review 기본값(`auto_save: true`)이면 서버가 저장까지 하므로 이 호출이 필요 없다. 불러도 멱등(이미 `saved`면 200 같은 응답).

### 추출 항목 편집 🔒  — 검토 화면에서 항목 단위 수정/삭제/추가
저장(save) 전에 1차 추출 결과(`canon_delta`)를 **항목 단위로** 고칠 수 있다.
**`extracted` 또는 `reviewed` 상태에서만** 가능하며, 캐논(`canon_*`)은 save 전까지 바뀌지 않는다.
편집 후의 최신 `canon_delta`가 이후 검수/저장의 기준이 된다.

- `category`: `worldview` | `characters` | `relations` | `timeline` | `spaces` | `events` | `foreshadowing`
- 각 항목의 정체성은 `entity_key`. 본문은 해당 category의 스키마로 검증된다.

```
PATCH  /projects/{id}/chapters/{cno}/delta/{category}/{entity_key}   // 수정 → 200, 갱신된 항목
POST   /projects/{id}/chapters/{cno}/delta/{category}                // 추가 → 201, 생성된 항목
DELETE /projects/{id}/chapters/{cno}/delta/{category}/{entity_key}   // 삭제 → 204
```
- **화면:** 1차 탭 항목 "✏️ 수정하기 → ✓ 검토 완료로 표시"(PATCH, 고친 내용은 그 항목의 실제 필드로 — 매핑은 `frontend/delta-view.js` 의 `EDIT_FIELDS`, 복선만 `note`/`quote`) · ✕ 삭제(DELETE). 추가(POST)는 화면에 없다
```json
// 예) 세계관 항목 추가 — POST .../delta/worldview
{ "entity_key": "magic", "item": "마법이 존재한다", "detail": "..." }
// 응답 201 (생성된 항목)
{ "entity_key": "magic", "item": "마법이 존재한다", "detail": "..." }
```
- 카테고리별 본문 필드는 result의 `canon_delta` 각 항목과 동일(예: characters=`name`/`group_name`/`attrs`, events=`label`/`stage`/`order_index`/`attrs` …).
  🆕5 `attrs`는 복선을 뺀 모든 카테고리에서 받는다(생략하면 `null` — 원본 `attrs`를 지우고 싶지 않으면 받은 값을 그대로 돌려보낸다).
- PATCH는 경로의 `entity_key`가 정체성 — 본문 `entity_key`가 다르면 400.
- 오류: 403(남의 자원) · 404(없는 entity_key) · 400(잘못된 category / 본문 검증 실패 / 경로·본문 불일치) · 409(saved 등 편집 불가 상태 / 추가 시 entity_key 중복)

> **⚠️ `reviewed` 상태에서 편집하면 자동으로 `extracted`로 되돌아간다.**
> 기존 모순(contradictions)은 편집 전 기준이라 **낡은 결과**이므로 서버가 삭제한다.
> → 프론트는 편집 후 `result`를 다시 조회하면 `status: "extracted"`(모순 없음)로 오므로,
> 사용자에게 **② 검수 버튼을 다시 노출**해 최신 델타 기준으로 재검수하게 한 뒤 저장한다.
> (캐논 병합은 여전히 save 에서만.)

---

## 4. 캐논 (자료정리 6탭)

`GET /projects/{id}/canon?view={탭}&at_chapter={N}` · 🆕5 `GET /projects/{id}/canon?view={탭}&chapter={N}`
- **화면:** 시각화 자료 탭. 회차 필터 "전체" = 파라미터 없음(현재 캐논), 회차 선택 = `chapter=N`
  (6개 카테고리 버튼 = 6뷰). 저장 전 회차는 캐논에 없으므로 회차 상세의 `canon_delta`로 그린다.
- `view` 값: `worldview`(세계관) · `characters`(인물) · `timeline`(시간) · `spaces`(공간) · `events`(사건) · `foreshadowing`(복선)
- 탭마다 데이터 형태가 다르다. 아래 예시 참고.
- 🆕 **모든 탭의 항목에 `entity_key`**(같은 항목을 회차 사이에서 잇는 논리 키)가 들어간다. 인물 노드·공간 항목에는 `attrs`도.
- 🆕 **`at_chapter=N` — 시점 조회.** N화까지 저장된 시점의 캐논을 돌려준다(그 뒤 회차에서 바뀐 설정은 바뀌기 전 값으로).
  생략하면 지금(최신) 캐논. `0`이면 빈 결과, 음수는 400.
  ```
  예) 1화: 한서진 = 32세 대장장이 → 2화: 45세 약초상 → 3화: 북쪽 언덕 오두막
      ?view=characters&at_chapter=1 → 32세 대장장이 버전
      ?view=characters&at_chapter=2 → 45세 약초상 버전
      ?view=characters              → 3화 버전(현재)
  ```
  - 저장된 회차를 재업로드·재저장해 빠진 항목은 그 회차 시점부터 보이지 않고,
    그 항목의 이전 회차 버전이 있으면 그 버전이 다시 보인다.
- 🆕5 **`chapter=N` — 회차 기여 조회.** N화가 캐논에 넣은 행 **전부**를 돌려준다. `at_chapter`(그 시점에 유효한 버전, 항목당 1행)와
  달리 이후 회차에서 바뀌거나 재저장으로 빠진 버전도 포함되므로, 한 `entity_key`가 여러 번 올 수 있다.
  `superseded_at_chapter`(몇 화에서 대체/철회됐나, 현재 버전이면 `null`)와 `is_current`로 구분한다.
  `at_chapter`와 함께 주면 400, `0` 이하도 400. 기여가 없는 회차(저장 전, 전부 unchanged)는 빈 결과.
  ```
  예) 1화 저장: RULE_001 v1 … → 2화에서 RULE_001 수정 저장
      ?view=worldview&chapter=1 → 1화의 모든 규칙. RULE_001 은 v1, is_current:false, superseded_at_chapter:2
      ?view=worldview&chapter=2 → RULE_001 v2 하나 (나머지는 1화와 같아 2화 기여가 아님)
  ```
- 🆕5 **모든 탭의 항목에 `version`·`is_current`·`superseded_at_chapter`**, 복선을 뺀 탭(엣지 포함)에는 `attrs`.
  `attrs` 키는 위 "결과 조회"의 표와 같다(저장 전 `canon_delta`와 같은 모양). 기존 필드는 그대로.

### 세계관 — `view=worldview`
```json
{ "view": "worldview",
  "items": [ { "id": "uuid", "entity_key": "RULE_001", "item": "화폐 단위는 '냥'", "detail": "...",
               "attrs": { "certainty": "explicit", "source_text": "..." },
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null } ] }
```

### 인물 — `view=characters` (관계 그래프)
```json
{ "view": "characters",
  "nodes": [ { "id": "c1", "entity_key": "c1", "name": "회장", "group": "경영진",
               "attrs": { "traits": [ { "trait": "예순 살", "trait_type": "appearance", "certainty": "explicit" } ],
                          "description": "...", "aliases": [], "certainty": "explicit", "source_text": "..." },
               "source_chapter": 1, "version": 2, "is_current": true, "superseded_at_chapter": null },
             { "id": "c2", "entity_key": "c2", "name": "부회장", "group": "경영진", "attrs": null,
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null } ],
  "edges": [ { "entity_key": "c1->c2", "from": "c1", "to": "c2", "relation": "상하관계",
               "attrs": { "relationship_type": "상하관계", "sentiment": "neutral", "description": "...", "certainty": "explicit", "source_text": "..." },
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null } ] }
```
- 프론트: `nodes`/`edges`로 관계도 렌더링(그룹은 묶음 표시)
- 🆕 노드에 `entity_key`(= `id`), `attrs`, `source_chapter`(이 버전이 들어온 회차), `version`이 추가됐다. 엣지에 `entity_key`.
- 🆕5 `attrs.traits`는 `{trait, trait_type, certainty}` 객체 배열(0005 이전에 저장된 캐논은 문자열 배열일 수 있다 — 둘 다 받을 것).
  엣지에도 `attrs`(`relationship_type`/`sentiment`/`description`)와 버전 메타. `chapter=N`에선 `from`/`to`가 다른 회차 노드를 가리킬 수 있다.

### 시간 — `view=timeline`
```json
{ "view": "timeline",
  "items": [ { "id": "uuid", "entity_key": "TIME_001", "scene_label": "S#1", "order_index": 1, "time_value": "1일차 아침",
               "attrs": { "description": "...", "certainty": "explicit", "source_text": "..." },
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null } ] }
```

### 공간 — `view=spaces`
```json
{ "view": "spaces",
  "items": [ { "id": "uuid", "entity_key": "LOCATION_001", "scene_label": "S#1", "place": "산속 연못",
               "attrs": { "description": "...", "certainty": "explicit", "source_text": "..." },
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null } ] }
```

### 사건 — `view=events`
```json
{ "view": "events",
  "items": [ { "id": "uuid", "entity_key": "EVENT_001", "label": "도끼를 연못에 빠뜨림", "stage": "암시", "order_index": 1,
               "attrs": { "summary": "...", "cause": "...", "result": "...", "main_actor_character_id": "c1",
                          "participant_character_ids": ["c1"], "certainty": "explicit", "source_text": "..." },
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null },
             { "id": "uuid", "entity_key": "EVENT_002", "label": "산신령 등장", "stage": "궁지1", "order_index": 2, "attrs": null,
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null } ] }
```
- `stage`: 서사 구조 단계(암시 / 궁지1 / 궁지2 / 절정 …)

### 복선 — `view=foreshadowing` (트리)
```json
{ "view": "foreshadowing",
  "items": [ { "id": "f1", "entity_key": "f1", "label": "정직함 강조", "parent_id": null, "kind": "setup",
               "source_chapter": 1, "version": 1, "is_current": true, "superseded_at_chapter": null },
             { "id": "f2", "entity_key": "f2", "label": "정직함으로 보상받음", "parent_id": "f1", "kind": "payoff",
               "source_chapter": 3, "version": 1, "is_current": true, "superseded_at_chapter": null } ] }
```
- `kind`: `setup`(설치) / `payoff`(회수). `parent_id`로 트리 구성
- 🆕5 복선만 `attrs`가 없다(LLM 원본 포맷에 복선이 없다).

---

## 5. 연동 시 자주 막히는 곳 (체크리스트)

- [ ] **CORS** — 백엔드가 프론트 도메인(`localhost:3000` 등)을 허용했는지. 안 되면 콘솔에 CORS 에러. → 백엔드에 알리기
- [ ] **토큰 첨부** — 401이 뜨면 `Authorization: Bearer` 헤더 빠졌거나 만료. 로그인 화면으로 보내기
- [ ] **폴링 종료 조건** — result `status`가 `reviewed`/`saved`/`failed`가 되면 폴링 멈추기 (🆕2 auto_save면 `saved`까지 간다)
- [ ] **분석 중복 요청** — 409에 `current_status`가 있으면 새로 시작하지 말고 기존 작업 폴링
- [ ] **베이스 URL** — 하드코딩 말고 `.env`로
- [ ] **에러 형태** — 항상 `{ "detail": "..." }` 하나로 처리 (🆕 중복 업로드 409만 `existing_chapter_no`가 더 온다)
- [ ] **중복 업로드** — 같은 원고를 다른 회차 번호로 올리면 409. 클라이언트에서 따로 해시를 비교할 필요 없다
- [ ] **저장 전 이탈 경고** — `reviewed` 상태 이탈 시 팝업
- [ ] 🆕5 **시각화 데이터 출처** — 저장 전 회차는 `result.canon_delta`, 저장 후 회차는 `GET /canon?chapter=N`, 전체는 `GET /canon`. `/visual`은 기준이 아니다

---

## 6. 백엔드가 켜져 있으면 여기서 직접 확인

- `GET /docs` — Swagger UI. 브라우저에서 API를 직접 호출해보며 응답 확인 가능
- `GET /openapi.json` — 기계가 읽는 스펙. 이걸로 타입 클라이언트 자동 생성(openapi-typescript, orval 등) 가능

> 이 문서와 `/openapi.json`이 다르면 **`/openapi.json`이 정답**이다 (코드에서 자동 생성되므로).
