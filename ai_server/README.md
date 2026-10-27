# glitch-ai

Glitch 백엔드(저장소 루트)가 HTTP 로 호출하는 **LLM 분석 파이프라인 서버**.

몸통과의 계약은 HTTP 엔드포인트 세 개(`POST /extract`, `POST /review`, `GET /health`)와
그 입출력 스키마(`app/pipeline/interface.py`, 이 서버의 `server/schemas.py` 가 미러) 뿐이다.
그 안쪽(프롬프트·모델·검색 방식)은 이 서버의 자유다.

> 이 문서는 **실행 방법**만 다룬다.
> 구조·설계 배경·현재 상태·남은 일은 [AI_SERVER.md](AI_SERVER.md) 를 본다.

```
프론트 ──▶ 몸통(:8000) ──HTTP──▶ 이 서버(:8100) ──▶ Claude
                 ▲                      │
                 └──── rich JSON ───────┘
```

## 엔드포인트

| | 요청 | 응답 |
|---|---|---|
| `POST /extract` | `chapter_text`, `canon`, `title`, `chapter_no` | prompt_result_1 rich JSON |
| `POST /review` | `+ delta` | `{"contradictions": [...]}` (스키마 고정) |
| `GET /health` | — | 현재 모드 |

`chapter_no` 는 이번 회차 번호다(scope_ai 가 회차별 상태를 쌓는 키). 안 오면
`canon.up_to_chapter + 1` 로 추정하고 경고를 남긴다.

`/extract` 응답은 scope_ai 의 ep 를 global ID(`CHAR_001` …)로 바꾸고 `times[].expression`
을 채운 rich JSON 이다. 몸통의
`looks_like_visual_json()` 이 잡아서 `CanonDelta` 로 변환하고, 원본은
`analysis_results.raw_output` 에 보존돼 `GET /visual` 로 프론트에 내려간다.

`/review` 는 자동 변환이 없다. 필드 하나만 어긋나도 몸통에서 터지므로
`server/schemas.py` 의 `ReviewResponse` 를 정확히 지킬 것.

## 모드

`.env` 에서 엔드포인트별로 따로 켠다.

> ⚠️ **주의 — echo 가 기본값이다 (`.env.example`).** echo 모드는 **원고와 무관하게** 항상 같은
> 샘플(`server/sample_visual.json`, 헤일트라움 이야기)을 돌려준다. 화면에는 인물·사건이 그럴듯하게
> 채워지지만 **실제 분석 결과가 아니다** — 모든 회차가 같은 추출 결과가 된다. 실데이터를 보려면
> `EXTRACT_MODE=llm`, `REVIEW_MODE=llm` 으로 띄우고, 지금 어느 모드인지는 `GET /health` 로 확인한다.

| | `echo` | `llm` |
|---|---|---|
| `/extract` | `server/sample_visual.json` 반환 | scope_ai: Claude 구조화 → ID 통합 |
| `/review` | 원문 앞부분을 문 더미 모순 1건 | scope_ai: 임베딩 → ERS Top-K → Claude 검토 |

llm 모드의 로직은 `scope_ai/` 에 있다. AI 파트 저장소
(`a01038007367-pixel/weave`, `AI` 브랜치 `Project_scope_AI_refactored`, 29aa068)의
사본이며 **직접 고치지 않는다** — 몸통 계약에 맞추는 변환은 전부
`server/scope_bridge.py` 에서 한다. 업스트림이 바뀌면 `scope_ai/` 만 다시 덮어쓴다.

검수 임베더는 `EMBEDDING_MODE` 로 고른다. `bge` = BGE-M3(운영, torch 필요),
`hash` = 설치 없이 도는 가짜(배선 확인용, 의미 유사도 없음).

**`echo` 는 임시 구현이 아니라 상시 유지하는 스위치다.**

- 분석이 깨졌을 때 `echo` 로 돌려서 되면 LLM 문제, 안 되면 배선 문제 — 1분에 갈린다
- API 키 없는 팀원도 프론트/몸통 전 구간을 돌릴 수 있다
- 응답이 결정적이라 자동 테스트를 붙일 수 있다

> 몸통의 `PIPELINE_MODE=fake` 와는 다르다. `fake` 는 HTTP 를 타지 않아
> "몸통 로직이 맞나"를 보고, `echo` 는 "몸통↔AI 배선이 맞나"를 본다.

## 실행

```
run.bat                     (= uvicorn server.main:app --port 8100 --reload)
```

## 확인 방법 — 비용 순서대로

**0. 단위 테스트 (LLM·torch 없음, 무료)**

```
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

**1. 서버만 확인 (LLM 호출 없음, 무료)**

```
curl http://127.0.0.1:8100/health
```

**2. Claude 통로 확인 (max_tokens=1, 사실상 무료)**

```
curl http://127.0.0.1:8100/health/llm
```

키가 유효한지, 네트워크가 열렸는지, 모델명이 맞는지만 본다.
평소 "붙어 있나?" 확인은 여기까지만 한다.

**3. 배선 검증 (echo 모드면 무료, llm 모드면 실제 호출)**

몸통의 `RemotePipeline` 로 이 서버를 호출한다. DB·Redis·프론트 없이 계약만 본다.

```
.venv\Scripts\python.exe ai_server\check_contract.py
.venv\Scripts\python.exe ai_server\check_contract.py ai_server\sample_chapter.txt
```

**4. 검수 품질 시나리오 (실제 호출 3회)**

심어둔 모순 2건은 잡는지, 함정 2건(인물의 성장 / 새 정보 추가)은 안 잡는지 본다.
**프롬프트를 고쳤을 때만** 돌린다.

```
.venv\Scripts\python.exe ai_server\check_review.py
```

> 비용이 들지 않게 개발하려면 `.env` 에서 `EXTRACT_MODE=echo`, `REVIEW_MODE=echo`
> 로 되돌린다. 프론트·몸통 작업은 echo 로 충분하다.

## 다음 단계

1. **[완료]** echo 배선 — 몸통 ↔ AI 서버 왕복
2. **[완료]** `EXTRACT_MODE=llm` — 실제 Claude 1차 추출
3. **[완료]** `prompt/review_prompt.txt` 작성 + `REVIEW_MODE=llm`
4. **[완료 2026-10-12]** 프론트 하드코딩 해제 — 시각화 탭이 몸통 `GET /chapters/{no}/visual`·`GET /canon` 실데이터로 그린다
5. **[완료 2026-10-03]** llm 모드 내부를 scope_ai(ID 통합 + BGE-M3 ERS)로 교체
6. scope_ai 업스트림 TODO — 세계관 규칙/인물 변화 병합, 회차 간 시간·공간 기준점 통합
7. 2차 검수 NDJSON 스트림 — `scope_bridge.review()` 가 이미 임베딩/탐지 두 단계로 나뉘어 있다

## 원칙

- **캐논의 진실 원천은 몸통 DB.** 이 서버는 DB 를 쓰지 않는다. 다만 scope_ai 가
  ID 통합·관련 사건 검색용 보조 색인(`Data/stories/{project_id}/`)을 파일로 쌓는다.
  같은 회차를 다시 추출하면 그 회차 흔적을 걷어내고 다시 쌓는다(멱등).
  이 폴더를 지워도 몸통 데이터는 안전하다 — 대신 이후 회차의 ID 통합·ERS 가 빈 상태에서 다시 시작한다.
- **`ANTHROPIC_API_KEY` 는 여기 `.env` 에만.** 몸통에는 URL 만 둔다.
- **오프셋은 서버가 계산한다.** LLM 에게 `start`/`end` 를 세라고 하지 말고
  `quote` 만 받아 `span_of()` 로 찾는다.
