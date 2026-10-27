# Glitch 아키텍처 (한 장 요약)

> 이 저장소를 처음 여는 세션이 먼저 읽는 문서다. 규칙은 [`CLAUDE.md`](../CLAUDE.md),
> API·상태값의 최신은 [`glitch_api_contract.md`](glitch_api_contract.md), 실행법은 [`README.md`](../README.md).
> 2026-10-13 기준 (융합 1~4단계 반영).

## 요청 흐름

```
브라우저 frontend/ (같은 오리진 /)
  script.js ─ store.js ─ api.js ──HTTP(JWT)──▶ app/api/*  (라우터: 입출력·검증만)
                                                   │
                                                   ▼
                                     app/service/* (비즈니스 로직·트랜잭션·소유권 검사)
                                       │                 │
                         app/repository/* (SQL)    app/workers/queue.py ──▶ Redis (arq)
                                       │                                       │
                                  PostgreSQL ◀── 상태·결과 저장 ── app/workers/tasks.py (워커 프로세스)
                                       ▲                                       │
                                       │                    AnalysisPipeline (app/pipeline/interface.py)
                                       │                       fake | local | remote ──HTTP──▶ ai_server/ :8100
                                       │                                                  /extract /review /health
                     캐논 병합 (save, chapters.status=saved 와 같은 트랜잭션, append-only 버전)
```

- 진행 상황은 `chapters.status` 하나로만 알 수 있다. 작업 창은 `GET /jobs/active`(status 파생)를 1.5초마다 폴링한다.
- 프론트는 브라우저 저장소에 테마·사이드바 접힘만 둔다. 토큰은 sessionStorage에 둔다.

## 상태 머신 (`chapters.status`)

| 상태 | 뜻 | 다음 |
|---|---|---|
| `uploaded` | 원문 업로드됨 | `POST /extract` → `extracting` |
| `extracting` | 1차 추출 중 (워커) | → `extracted` / `failed` |
| `extracted` | 추출 결과(canon_delta) 검토 대기, 항목 편집 가능 | `POST /review` → `reviewing` |
| `reviewing` | 2차 검수 중 (워커) | → `reviewed` / `failed` |
| `reviewed` | 모순 결과 나옴, 저장 대기 (편집하면 `extracted`로 되돌아감) | auto_save 또는 `POST /save` → `saved` |
| `saved` | 캐논에 병합됨 | 재검수 `POST /review` → `reviewing` |
| `failed` | 어느 단계든 실패 (`failed_stage`=extract\|review) | 다시 `extract`, 추출 결과가 있으면 `review` |

## 결정 기록 (D1~D16)

자세한 동작은 계약서 해당 절 참고.

| | 결정 | 계약서 |
|---|---|---|
| D1 | 회차 = 백엔드 챕터 1:1 (파일 1개·직접 입력 1건 = 회차 1개) | 3장 회차 업로드 |
| D2 | 저장(saved)된 회차의 추출 결과는 읽기 전용 | 3장 추출 항목 편집 |
| D3 | 중복 원고 판단은 서버 해시 → 409 + `existing_chapter_no` | 3장 회차 업로드 |
| D4 | 검수 뒤 자동 저장(`auto_save` 기본 true), 실패 시 reviewed → `POST /save` 재시도 | 3장 ② 검수 |
| D5 | 저장된 회차 재검수 허용(재업로드 없음, 모순·판정 초기화) | 3장 ② 검수 |
| D6 | 검수 비교 기준은 N-1화 시점 캐논 | 3장 ② 검수 |
| D7 | `/jobs/active`는 status에서 파생(별도 작업 기록 없음) | 3장 진행 중 작업 조회 |
| D8 | 진행 중 중복 요청은 409 + `current_status`, 고착 작업은 자동 정리 | 3장 분석 2단계 |
| D9 | 큐는 arq로 통일 (inline은 테스트 전용) | — |
| D10 | 저장 후 수정 = `auto_save:false` 재검수 → 편집 → review → saved | 3장 저장 후 수정 |
| D11 | 저장 순서가 회차 순서와 어긋나면 뒤 회차와는 대조하지 않음 | 3장 ② 검수 |
| D12 | 브라우저 저장소는 테마·사이드바만 | — |
| D13 | 예전 브라우저(localStorage) 데이터는 이관하지 않음 | — |
| D14 | 화면의 회차 번호 = 서버 `chapter_no` | 3장 회차 목록 |
| D15 | 1차 항목은 `entity_key`로 그 자리에서 즉시 PATCH/DELETE. 내용·인용 칸은 항목의 실제 필드(세계관 `detail`, 시간 `time_value`, 사건 `attrs.summary`, 인물·관계·공간 `attrs.description`, 인용 `attrs.source_text`)를 교체 → 저장 때 캐논·시각화에 반영 (2026-10-26, 이전엔 `note`/`quote`만). 복선만 `note`/`quote` | 3장 추출 항목 편집 |
| D16 | 작업 창은 서버 폴링(1.5초), 로그인 직후 `GET /jobs/active`로 복원 | 3장 진행 중 작업 조회 |
| D17 | 저장소 기본 DB는 compose `db`(127.0.0.1:5433). 네이티브 PostgreSQL은 선택 | README 빠른 시작 |

## 미결 사항

- 캐논 `attrs`가 버전업 때 통째로 바뀌어 이전 속성이 사라진다(합집합 병합 vs AI가 누적 반환).
- 장소 `entity_key`가 회차마다 새로 생긴다(ID 통합 미적용).
