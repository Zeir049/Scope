"""ERS 세부 feature 계산.

미확정 산식은 TODO와 함께 임시 규칙으로 분리해두었다.
해당 함수만 교체하면 ranking/calculator 코드는 건드리지 않아도 된다.
"""

from __future__ import annotations

from .math_utils import Score, cosine_similarity, weighted_average

# TODO: 실험 결과에 따라 내부 가중치 확정 필요.
PARTICIPANT_OVERLAP_WEIGHT = 0.70
MAIN_ACTOR_WEIGHT = 0.30


def semantic_feature(a_emb: dict, b_emb: dict) -> Score:
    """summary_A ↔ summary_B 임베딩 cosine."""
    return cosine_similarity(a_emb.get("summary_embedding"), b_emb.get("summary_embedding"))


def action_feature(a_emb: dict, b_emb: dict) -> Score:
    """title_A ↔ title_B 임베딩 cosine."""
    return cosine_similarity(a_emb.get("title_embedding"), b_emb.get("title_embedding"))


def causal_feature(a_emb: dict, b_emb: dict) -> Score:
    """A.cause↔B.result, B.cause↔A.result 양방향 비교.

    TODO: 두 방향을 평균/최댓값/방향성 가중합 중 어떤 방식으로 합칠지 확정 필요.
    현재는 사용 가능한 두 cosine의 단순 평균을 임시 사용한다.
    """
    a_cause_b_result = cosine_similarity(
        a_emb.get("cause_embedding"), b_emb.get("result_embedding")
    )
    b_cause_a_result = cosine_similarity(
        b_emb.get("cause_embedding"), a_emb.get("result_embedding")
    )
    return weighted_average([
        (a_cause_b_result, 0.5),
        (b_cause_a_result, 0.5),
    ])


def participant_feature(a_event: dict, b_event: dict) -> Score:
    """participant 교집합 비율 + main actor 일치 여부.

    TODO: participant/main actor 내부 가중치 확정 필요.
    현재 participant는 Jaccard similarity를 사용한다.
    """
    a_participants = set(a_event.get("participant_character_ids") or [])
    b_participants = set(b_event.get("participant_character_ids") or [])
    union = a_participants | b_participants
    overlap = len(a_participants & b_participants) / len(union) if union else None

    a_main = a_event.get("main_actor_character_id")
    b_main = b_event.get("main_actor_character_id")
    main_match = None
    if a_main is not None and b_main is not None:
        main_match = 1.0 if a_main == b_main else 0.0

    return weighted_average([
        (overlap, PARTICIPANT_OVERLAP_WEIGHT),
        (main_match, MAIN_ACTOR_WEIGHT),
    ])


def time_feature(a_time: dict | None, b_time: dict | None) -> Score:
    """time_info 기반 임시 시간 feature.

    주의: 현재 prompt의 time_info는 각 submission 내부 기준점에 대한 상대 좌표다.
    서로 다른 submission의 좌표는 아직 직접 비교할 수 없으므로 None을 반환한다.

    TODO: ep_global 기준 timeline anchor/offset 통합 규칙을 만든 뒤 cross-submission 계산 구현.
    같은 submission 안에서는 x 거리(0~9)를 0~1 유사도로 단순 변환한다.
    """
    if not a_time or not b_time:
        return None
    if a_time.get("source_submission") != b_time.get("source_submission"):
        return None
    a_info = a_time.get("time_info")
    b_info = b_time.get("time_info")
    if not (isinstance(a_info, list) and isinstance(b_info, list) and a_info and b_info):
        return None
    try:
        distance = abs(float(a_info[0]) - float(b_info[0]))
    except (TypeError, ValueError):
        return None
    return max(0.0, 1.0 - min(distance, 9.0) / 9.0)


def location_feature(a_location: dict | None, b_location: dict | None) -> Score:
    """location_info 기반 임시 공간 feature.

    주의: location_info 역시 submission별 기준점 좌표라 cross-submission 직접 비교가 안전하지 않다.
    TODO: 작품 전체 location anchor 통합 규칙 확정 후 교체.
    같은 submission에서는 x/y/z 차이를 이용한 임시 유사도를 사용한다.
    """
    if not a_location or not b_location:
        return None
    if a_location.get("source_submission") != b_location.get("source_submission"):
        return None
    a_info = a_location.get("location_info")
    b_info = b_location.get("location_info")
    if not (
        isinstance(a_info, list) and isinstance(b_info, list)
        and len(a_info) >= 3 and len(b_info) >= 3
    ):
        return None
    try:
        x_diff = abs(float(a_info[0]) - float(b_info[0]))
        y_diff = 0.0 if a_info[1] == b_info[1] else 1.0
        z_diff = 0.0 if a_info[2] == b_info[2] else 1.0
    except (TypeError, ValueError):
        return None
    # TODO: x/y/z 영향도 역시 추후 확정.
    distance = min(x_diff / 9.0 + 0.15 * y_diff + 0.10 * z_diff, 1.0)
    return 1.0 - distance
