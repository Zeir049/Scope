# ⚠️ SMOKE TEST (임시 모듈)

전체 스택이 실제로 도는지 확인하는 **일회용 스모크 테스트**입니다.
흐름: 로그인 → **내 프로젝트 아무거나 선택**(또는 프로젝트 없이) → 텍스트 입력 →
**가짜 LLM(에코)이 텍스트를 그대로 반환** → 입력과 같으면 **"ok"**(다르면 "mismatch") →
그 결과를 `smoke_checks` 테이블에 저장 → SQL로 "이 사용자가 ok를 받았는지" 확인.

- **판정**: `입력 텍스트 == LLM 응답` 이면 `ok`. 지금은 에코라 항상 같아 `ok`가 나온다.
- **모든 유저·프로젝트 대상**: 로그인한 사용자의 프로젝트 목록에서 골라 어느 프로젝트에든 적용.
- **진짜 LLM 연결 지점**: `app/smoke/llm.py`의 `fake_llm_roundtrip` 본문(`return text`)만
  실제 LLM 호출로 교체하면 판정·저장·화면은 그대로 동작.

**진짜 LLM 기능이 붙으면 이 폴더는 통째로 삭제합니다.** 나머지 코드와 완전히 격리돼 있어
(다른 모듈은 `app.smoke`를 import 하지 않음) 아래 4단계로 흔적 없이 제거됩니다.

---

## 사용법

1. 서버 기동: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`
   - 기동 시 `smoke_checks` 테이블이 없으면 자동 생성됩니다(idempotent).
2. 브라우저에서 **http://localhost:8000/smoke** 접속.
3. `[로그인]`(기본값 cho@example.com / glitch123) → **프로젝트 선택**(내 프로젝트 아무거나,
   `＋ 새 프로젝트 만들기`, 또는 `(프로젝트 없이)`) → 텍스트 입력 → `[전송]`.
4. 화면에 **결과: ok** 와 **LLM 응답(echo): <입력한 텍스트>** 가 뜨면 성공.

## DB 확인 쿼리

```sql
SELECT sc.id, u.email, sc.input_text, sc.response, sc.created_at
FROM smoke_checks sc
JOIN users u ON u.id = sc.user_id
ORDER BY sc.created_at DESC;
```

해당 사용자 행에 `response = 'ok'` 가 보이면 전 구간(요청→인증→서비스→가짜LLM→DB커밋) 성공.

psql 예시:
```
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -U glitch -d glitch -c "SELECT sc.id, u.email, sc.input_text, sc.response, sc.created_at FROM smoke_checks sc JOIN users u ON u.id = sc.user_id ORDER BY sc.created_at DESC;"
```

---

## 삭제 방법 (4단계 — 흔적 없이 제거)

1. **`app/main.py`** 에서 smoke 관련 2줄 제거:
   - lifespan 안: `if settings.enable_smoke: ... await ensure_smoke_table()` 블록
   - 라우터 등록부: `if settings.enable_smoke: ... app.include_router(smoke_router)` 블록
2. **`app/core/config.py`** 에서 `enable_smoke` 필드 1줄 제거.
3. DB에서 테이블 드롭:
   ```sql
   DROP TABLE smoke_checks;
   ```
4. **`app/smoke/`** 폴더 삭제.

> 이 테이블은 의도적으로 Alembic 마이그레이션 체인 **밖**에 있습니다(자체 `ensure_smoke_table` 로 생성).
> 그래서 스모크 모듈이 살아있는 동안 `alembic revision --autogenerate` 를 돌리면
> `smoke_checks` 를 DROP 하려는 마이그레이션이 잡힐 수 있으니, 그 경우 해당 diff는 무시하세요.
> (모듈을 위 4단계로 제거하면 이 주의점도 사라집니다.)
