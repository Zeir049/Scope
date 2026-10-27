"""백엔드에서 전체 단계를 한 번에 호출하고 싶을 때 사용하는 선택적 오케스트레이터."""

from __future__ import annotations

from pathlib import Path

from .analysis import analyze_submission
from .id_split import process_ep
from .embedding import embed_submission_events
from .ers import rank_related_events
from .review import review_submission


def run_submission_pipeline(
    story_id: str,
    submission_number: int,
    submission_text: str,
    *,
    top_k: int = 5,
    data_root: str | Path | None = None,
) -> dict:
    ep = analyze_submission(
        story_id,
        submission_number,
        submission_text,
        data_root=data_root,
    )
    split_result = process_ep(
        story_id,
        submission_number,
        ep=ep,
        data_root=data_root,
    )
    embedding_result = embed_submission_events(
        story_id,
        submission_number,
        data_root=data_root,
    )
    ers_result = rank_related_events(
        story_id,
        submission_number,
        top_k=top_k,
        data_root=data_root,
    )
    review_result = review_submission(
        story_id,
        submission_number,
        data_root=data_root,
    )
    return {
        "analysis": ep,
        "id_split": split_result,
        "embedding": embedding_result,
        "ers": ers_result,
        "review": review_result,
    }
