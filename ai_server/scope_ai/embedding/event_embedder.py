"""ERS에서 임베딩 비교가 필요한 사건 필드만 벡터화."""

from __future__ import annotations

from .base import BaseEmbedder


EMBEDDING_FIELDS = ("title", "summary", "cause", "result")


def embed_events(events: list[dict], embedder: BaseEmbedder) -> list[dict]:
    results = [
        {
            "event_id": event.get("event_id"),
            "source_submission": event.get("source_submission"),
            **{f"{field}_embedding": None for field in EMBEDDING_FIELDS},
        }
        for event in events
    ]

    for field in EMBEDDING_FIELDS:
        texts: list[str] = []
        indexes: list[int] = []
        for index, event in enumerate(events):
            value = event.get(field)
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
                indexes.append(index)
        if not texts:
            continue
        vectors = embedder.embed_batch(texts)
        for index, vector in zip(indexes, vectors):
            results[index][f"{field}_embedding"] = vector

    return results
