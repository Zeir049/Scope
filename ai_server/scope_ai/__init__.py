"""Scope AI pipeline package.

각 단계는 하위 패키지에서 독립적으로 import한다.
루트 import 시 LLM/embedding 같은 무거운 선택 의존성을 강제로 로드하지 않는다.
"""
