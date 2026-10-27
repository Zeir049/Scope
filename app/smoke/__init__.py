# ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 삭제. 삭제법은 app/smoke/README.md 참조
"""전체 스택 일회용 스모크 테스트 (격리 모듈).

이 폴더 전체가 임시다. 나머지 코드는 이 패키지를 import 하지 않으며,
app/main.py 의 2줄(조건부 라우터 등록 + lifespan 테이블 생성)만 이 패키지를
가리킨다. 제거는 README.md의 4단계로 흔적 없이 가능.
"""
