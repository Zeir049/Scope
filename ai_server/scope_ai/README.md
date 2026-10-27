# Scope AI refactored pipeline

사용자 입력을 `submission`, LLM 구조화 결과를 `ep`, 작품 전체 최신 누적 상태를 `ep_global`로 통일한 버전입니다.

## 단계

1. `scope_ai.analysis.analyze_submission`
   - `submissionN.txt` 저장
   - LLM 분석 후 `epN.json` 저장
2. `scope_ai.id_split.process_ep`
   - `epN`을 5개 field 파일로 분리
   - 타입별 ID 통합
   - `ep_global.json` 갱신
3. `scope_ai.embedding.embed_submission_events`
   - 신규 submission 사건의 `title/summary/cause/result`만 증분 임베딩
4. `scope_ai.ers.rank_related_events`
   - 신규 사건별 이전/선행 사건 ERS 계산
   - feature 원값 + 중간 점수 + 최종 점수 저장
   - Top-K 저장
5. `scope_ai.review.review_submission`
   - 신규 사건 + ERS Top-K 사건을 LLM에 전달
   - 모순/설정 누수 검토 결과 저장

## 저장 구조

```text
Data/stories/{story_id}/
├─ submissions/submission1.txt
├─ episodes/ep1.json
├─ split/ep1/
│  ├─ worldview_rules.json
│  ├─ characters.json
│  ├─ events.json
│  ├─ times.json
│  └─ locations.json
├─ ep_global.json
├─ embeddings/event_embeddings.json
├─ ers/ers1.json
└─ reviews/review1.json
```

## 백엔드 import

```python
from scope_ai.analysis import analyze_submission
from scope_ai.id_split import process_ep
from scope_ai.embedding import embed_submission_events
from scope_ai.ers import rank_related_events
from scope_ai.review import review_submission
```

또는 전체 실행:

```python
from scope_ai.pipeline import run_submission_pipeline
```

## 현재 TODO

- 동일 세계관 규칙 병합 정책
- 동일 캐릭터의 변화 정보 병합 정책
- causal 두 방향 cosine 결합 방식
- participant overlap / main actor 내부 가중치
- submission 간 `time_info` 기준점 통합
- submission 간 `location_info` 기준점 통합

`time/location`은 서로 다른 submission끼리 상대 좌표를 직접 비교하지 않도록 현재 `None` 처리하며, ERS의 `weighted_average`가 해당 feature를 제외하고 가중치를 재정규화합니다.
