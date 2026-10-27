"""3단계: 신규 submission의 사건만 증분 임베딩하여 누적 저장."""

from __future__ import annotations

from pathlib import Path

from ..common import StoryPaths, load_json, save_json
from .base import BaseEmbedder
from .event_embedder import EMBEDDING_FIELDS, embed_events


def embed_submission_events(
    story_id: str,
    submission_number: int,
    *,
    data_root: str | Path | None = None,
    embedder: BaseEmbedder | None = None,
) -> dict:
    paths = StoryPaths(story_id, Path(data_root)) if data_root else StoryPaths(story_id)
    global_ep = load_json(paths.ep_global)
    new_events = [
        event for event in global_ep["events"]
        if event.get("source_submission") == submission_number
    ]

    if embedder is None:
        # sentence-transformers는 실제 임베딩 단계에서만 로드한다.
        from .bge_m3 import BGEM3Embedder
        model: BaseEmbedder = BGEM3Embedder()
    else:
        model = embedder

    new_embeddings = embed_events(new_events, model)

    if paths.event_embeddings.exists():
        store = load_json(paths.event_embeddings)
    else:
        store = {
            "model": getattr(model, "model_name", model.__class__.__name__),
            "embedding_fields": list(EMBEDDING_FIELDS),
            "events": [],
        }

    by_id = {item["event_id"]: item for item in store.get("events", [])}
    for item in new_embeddings:
        by_id[item["event_id"]] = item
    store["events"] = list(by_id.values())
    save_json(store, paths.event_embeddings)

    return {
        "submission_number": submission_number,
        "embedded_event_ids": [item["event_id"] for item in new_embeddings],
        "embedding_path": str(paths.event_embeddings),
    }
