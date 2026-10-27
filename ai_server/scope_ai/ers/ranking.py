"""신규 사건별 과거/선행 사건 ERS를 계산하고 Top-K를 저장."""

from __future__ import annotations

from pathlib import Path

from ..common import StoryPaths, load_json, save_json
from .calculator import calculate_ers
from .features import (
    semantic_feature,
    action_feature,
    causal_feature,
    participant_feature,
    time_feature,
    location_feature,
)


def _index(items: list[dict], field: str) -> dict[str, dict]:
    return {item[field]: item for item in items if item.get(field)}


def _eligible_target(source: dict, target: dict, submission_number: int, include_same_submission_previous: bool) -> bool:
    target_submission = target.get("source_submission")
    if target_submission is None:
        return False
    if target_submission < submission_number:
        return True
    if not include_same_submission_previous or target_submission != submission_number:
        return False
    try:
        return int(target.get("order", 0)) < int(source.get("order", 0))
    except (TypeError, ValueError):
        return False


def rank_related_events(
    story_id: str,
    submission_number: int,
    *,
    top_k: int = 5,
    include_same_submission_previous: bool = True,
    data_root: str | Path | None = None,
) -> dict:
    paths = StoryPaths(story_id, Path(data_root)) if data_root else StoryPaths(story_id)
    ep = load_json(paths.ep_global)
    embedding_store = load_json(paths.event_embeddings)

    event_by_id = _index(ep["events"], "event_id")
    time_by_id = _index(ep["times"], "time_id")
    location_by_id = _index(ep["locations"], "location_id")
    emb_by_id = _index(embedding_store.get("events", []), "event_id")

    new_events = [
        event for event in ep["events"]
        if event.get("source_submission") == submission_number
    ]

    result_events: list[dict] = []
    for source in new_events:
        source_id = source["event_id"]
        source_emb = emb_by_id.get(source_id, {})
        source_time = time_by_id.get(source.get("time_id"))
        source_location = location_by_id.get(source.get("location_id"))

        candidates: list[dict] = []
        for target in ep["events"]:
            if target.get("event_id") == source_id:
                continue
            if not _eligible_target(source, target, submission_number, include_same_submission_previous):
                continue

            target_id = target["event_id"]
            target_emb = emb_by_id.get(target_id, {})
            semantic = semantic_feature(source_emb, target_emb)
            action = action_feature(source_emb, target_emb)
            causal = causal_feature(source_emb, target_emb)
            participant = participant_feature(source, target)
            time = time_feature(source_time, time_by_id.get(target.get("time_id")))
            location = location_feature(source_location, location_by_id.get(target.get("location_id")))

            score = calculate_ers(
                semantic=semantic,
                action=action,
                causal=causal,
                participant=participant,
                time=time,
                location=location,
            )
            candidates.append({
                "event_id": target_id,
                **score,
            })

        candidates.sort(
            key=lambda item: item["relatedness"] if item["relatedness"] is not None else float("-inf"),
            reverse=True,
        )
        result_events.append({
            "source_event_id": source_id,
            "top_k": candidates[:top_k],
        })

    output = {
        "story_id": story_id,
        "submission_number": submission_number,
        "top_k": top_k,
        "events": result_events,
        "notes": [
            "각 ERS 결과에 feature 원값을 함께 저장함.",
            "cross-submission time/location은 기준점 통합 전까지 None이며 가중치 재정규화로 제외됨.",
        ],
    }
    save_json(output, paths.ers_result(submission_number))
    return output
