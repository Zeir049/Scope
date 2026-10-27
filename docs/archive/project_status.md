> **2026-07-02 기준 문서, 현재 구조와 다름** — 융합 이전 백엔드 단독 현황. 최신은 [`../ARCHITECTURE.md`](../ARCHITECTURE.md) 참고.

# Glitch 백엔드 — 프로젝트 현황 (목표 / 완성도 / 남은 일)

> 작성: 2026-07-02 · 대상: `C:\glitch_backend`
> 근거: CLAUDE.md 규칙, `docs/glitch_backend_spec.md`, 피그마 프로토타입, 코드 리뷰

---

## 1. 무엇을 하려고 했나 (목표와 범위)

**Glitch**는 장편 서사(웹소설 등)의 세계관·설정 **모순을 잡아주는 AI 서비스**다.
이 코드베이스는 그 서비스의 **백엔드 몸통(게이트웨이)** 이며, 책임은 다음과 같다.

- 인증(회원가입/로그인)
- 프로젝트(작품)·회차 관리
- 원문 저장
- **파이프라인 중개** — 회차 텍스트 + 기존 캐논을 분석기에 넘김
- **결과 저장(캐논 병합)** — 분석 결과를 누적 설정 DB에 반영

**범위 밖(의도적 제외):** 실제 모순 검출 LLM 로직. 이것은 인터페이스 뒤의 별도 영역이며,
몸통은 그 내부를 모른 채 "계약(interface)"으로만 호출한다.

**설계 원칙:** 레이어 분리(api→service→repository→models), 바뀔 것(LLM·메일·저장·프론트)은
전부 인터페이스/설정 뒤로 숨겨 나중에 무엇을 갈아끼워도 핵심 로직은 안 건드리게 한다.

---

## 2. 어디까지 완성됐나

### 2-1. 핵심 루프 — 완성 ✅
회원 → 드라이브 → 회차 업로드 → 분석 → 검토 → 저장 → 자료정리 6탭. 모든 화면에 대응 API 존재.

| 기능 | 엔드포인트 |
|------|-----------|
| 인증 | `POST /auth/register`·`login`·`logout`·`forgot-password`·`reset-password`, `GET /me` |
| 드라이브(검색+페이지) | `GET /projects?page=&q=` |
| 프로젝트 | `POST /projects`, `GET /projects/{id}`, `DELETE /projects/{id}` |
| 회차 | `GET/POST /projects/{id}/chapters` |
| 분석·결과·저장 | `POST .../{cno}/analyze`, `GET .../{cno}/result`, `POST .../{cno}/save` |
| 자료정리 6탭 | `GET .../canon?view=worldview\|characters\|timeline\|spaces\|events\|foreshadowing` |

### 2-2. 확장 6기능 — 구현 완료 ✅ (지난 리뷰의 갭 전부 반영)
- **프로젝트 수정 + 썸네일:** `PATCH /projects/{id}`, `POST /projects/{id}/thumbnail`
- **docx 업로드:** 확장자→파서 레지스트리(`parsing/registry.py`), txt/md/docx 지원
- **워크스페이스 챗:** `GET/POST /projects/{id}/chats`, `.../chats/{sid}/messages`
- **구독:** `GET/PUT /me/subscription` (free/pro plan)
- **공유 링크:** `POST /projects/{id}/share`, `GET .../shares`, `DELETE /shares/{id}`, 공개뷰 `GET /shared/{token}`
- **알림:** `GET /notifications`, `POST /notifications/read-all`, `POST /notifications/{id}/read`
- **비밀번호 재설정:** 토큰 발급→메일→검증. 토큰은 **해시로만 저장**, 만료·1회용 처리.

### 2-3. 구조·견고성 — 양호 ✅
- 레이어 규칙·타입힌트·async·도메인 예외·설정 중앙화 준수.
- 교체 가능 지점을 전부 **Protocol + 팩토리 주입**으로 통일: 파이프라인(`PIPELINE_MODE`),
  챗(`CHAT_MODE`), 메일(`EMAIL_MODE`), 저장(`STORAGE_MODE`). 기능 플래그도 존재.
- **캐논 불변식 강화:** `(project_id, entity_key) WHERE is_current` **부분 유니크 인덱스**를
  0002 마이그레이션에 추가 + 병합 순서를 "옛 행 false flush → 새 행 insert"로 정렬.
- 새 엔드포인트마다 **소유권 검사(`assert_owned`)** 적용.

### 2-4. 현재 실행 상태
`PIPELINE_MODE=fake`, `CHAT_MODE=fake`, `EMAIL_MODE=console`, `STORAGE_MODE=local` 기본값으로
**데모 실행 가능**. 시드(금도끼 은도끼 1~4화)도 자동 주입.

---

## 3. 뭘 해야 하나 (남은 일)

### A. 먼저 — 실제 실행/테스트 검증 (미확인 항목)
새로 추가된 테스트 통과 여부와 호스트 import가 아직 실검증되지 않음.
```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head     # 0002 인덱스까지 반영
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
.\.venv\Scripts\python.exe -m pytest -q
```
서버 기동 + `/docs`에 새 엔드포인트 노출 + pytest 초록불이면 백엔드 단계 종료로 본다.

### B. "비워둔 자리" 실제 구현으로 교체 (실서비스 전환 시)
설계상 인터페이스만 있고 실제 구현이 빈 곳. 준비되는 대로 설정만 바꿔 끼운다.
- **진짜 모순 검출 파이프라인** — `PIPELINE_MODE=remote` + `PIPELINE_REMOTE_URL`, 입출력 JSON 스키마 합의. (가장 중요)
- **챗 어시스턴트 LLM** — `RemoteChatAssistant` 추가 후 `CHAT_MODE=remote`.
- **메일 발송** — `SmtpEmailSender` 추가 후 `EMAIL_MODE=smtp`(비번 재설정 메일 실제 발송).
- **파일 저장** — `S3Storage` 추가 후 `STORAGE_MODE=s3`(썸네일/원문 클라우드 저장).

### C. 프론트엔드 연결
백엔드는 `docs/glitch_api_contract.md`(= `/openapi.json`) 계약대로 구현됨.
프론트를 받으면 `CORS_ORIGINS`에 도메인 추가 + 프론트의 Base URL만 맞추면 붙는다.

### D. 실서비스 하드닝(운영 전)
- `JWT_SECRET`·DB 비번 등 비밀값을 운영 값으로 교체(기본값 금지).
- 비동기 분석을 BackgroundTasks → arq/Celery로 이전(무거운 실제 파이프라인 대비). 코드는 이전 쉽게 설계됨.
- 테스트 격리 개선: 외부 Postgres 의존/롤백 격리 없음 → CI 자동화 시 스키마 자동생성·트랜잭션 롤백 픽스처 추가 권장.
- (선택) 회원가입 약관동의, 알림 트리거 연결 등 UI 부수 요소.

---

## 한 줄 요약
> **백엔드 몸통은 사실상 완성**되어 fake 모드로 데모 가능한 상태다. 남은 일은
> ①실행/테스트 검증 ②비워둔 자리(진짜 파이프라인·챗·메일·저장) 교체 ③프론트 연결 ④운영 하드닝.
