from __future__ import annotations

from math import sqrt
from typing import Optional

Score = Optional[float]


def weighted_average(items: list[tuple[Score, float]]) -> Score:
    valid = [(score, weight) for score, weight in items if score is not None]
    if not valid:
        return None
    denominator = sum(weight for _, weight in valid)
    if denominator == 0:
        return None
    return sum(score * weight for score, weight in valid) / denominator


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> Score:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    # BGE-M3 vectors are normalized, but calculate robustly anyway.
    return dot / (norm_a * norm_b)
