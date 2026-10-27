"""4단계의 순수 ERS 수식 계산부."""

from __future__ import annotations

from .math_utils import Score, weighted_average


def calculate_similarity(semantic: Score, action: Score) -> Score:
    return weighted_average([(semantic, 0.70), (action, 0.30)])


def calculate_context(participant: Score, time: Score, location: Score) -> Score:
    """최신 수식: world 제거, participant 0.50 / time 0.30 / location 0.20."""
    return weighted_average([
        (participant, 0.50),
        (time, 0.30),
        (location, 0.20),
    ])


def calculate_ers(
    *,
    semantic: Score,
    action: Score,
    causal: Score,
    participant: Score,
    time: Score,
    location: Score,
) -> dict:
    similarity = calculate_similarity(semantic, action)
    context = calculate_context(participant, time, location)
    relatedness = weighted_average([
        (similarity, 0.30),
        (causal, 0.45),
        (context, 0.25),
    ])

    # feature 원값도 반드시 함께 보존한다.
    return {
        "relatedness": relatedness,
        "similarity": similarity,
        "causal": causal,
        "context": context,
        "features": {
            "semantic": semantic,
            "action": action,
            "causal": causal,
            "participant": participant,
            "time": time,
            "location": location,
        },
    }
