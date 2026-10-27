"""5단계: 신규 사건 + ERS Top-K 선행 사건을 LLM으로 검토."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from ..analysis.llm_client import call_claude
from ..common import StoryPaths, load_json, load_text, save_json


DEFAULT_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "review_prompt.txt"


def _index(items: list[dict], field: str) -> dict[str, dict]:
    return {item[field]: item for item in items if item.get(field)}


def build_review_payload(ep: dict, ers_result: dict) -> dict:
    events = _index(ep["events"], "event_id")
    characters = _index(ep["characters"], "character_id")
    times = _index(ep["times"], "time_id")
    locations = _index(ep["locations"], "location_id")

    def enrich(event_id: str) -> dict | None:
        event = events.get(event_id)
        if event is None:
            return None
        participant_ids = event.get("participant_character_ids") or []
        return {
            "event": event,
            "participants": [characters[cid] for cid in participant_ids if cid in characters],
            "time": times.get(event.get("time_id")),
            "location": locations.get(event.get("location_id")),
        }

    payload_events = []
    for item in ers_result.get("events", []):
        source_id = item["source_event_id"]
        payload_events.append({
            "source": enrich(source_id),
            "related": [
                {
                    "ers": candidate,
                    "data": enrich(candidate["event_id"]),
                }
                for candidate in item.get("top_k", [])
            ],
        })

    return {
        "submission_number": ers_result.get("submission_number"),
        "events": payload_events,
    }


def _parse_or_wrap(response_text: str) -> dict:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 리뷰 단계가 완전히 중단되지 않도록 raw 응답을 보존한다.
        return {"parse_error": True, "raw_text": response_text}


def review_submission(
    story_id: str,
    submission_number: int,
    *,
    data_root: str | Path | None = None,
    prompt_path: str | Path = DEFAULT_PROMPT,
    llm_callable: Callable[[str, str], str] | None = None,
) -> dict:
    paths = StoryPaths(story_id, Path(data_root)) if data_root else StoryPaths(story_id)
    ep = load_json(paths.ep_global)
    ers_result = load_json(paths.ers_result(submission_number))
    submission_text = paths.submission(submission_number).read_text(encoding="utf-8")
    payload = build_review_payload(ep, ers_result)

    user_text = (
        "===== 최신 submission 원문 =====\n"
        + submission_text
        + "\n\n===== 신규 사건 및 ERS 관련 사건 =====\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    prompt = load_text(prompt_path)
    caller = llm_callable or (lambda text, system: call_claude(text, system))
    response = caller(user_text, prompt)
    parsed = _parse_or_wrap(response)
    save_json(parsed, paths.review_result(submission_number))
    return parsed
