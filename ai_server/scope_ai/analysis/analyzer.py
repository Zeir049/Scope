"""1단계: submission 원문을 LLM으로 구조화하여 epN.json으로 저장."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .llm_client import call_claude
from ..common import StoryPaths, load_text, save_json, save_text, validate_ep


DEFAULT_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "analysis_prompt.txt"


def _parse_json_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM 응답을 JSON으로 파싱하지 못했습니다.") from exc

    validate_ep(data)
    return data


def analyze_submission(
    story_id: str,
    submission_number: int,
    submission_text: str,
    *,
    data_root: str | Path | None = None,
    prompt_path: str | Path = DEFAULT_PROMPT,
    llm_callable: Callable[[str, str], str] | None = None,
) -> dict:
    """사용자 원문을 submissionN.txt로 저장하고 분석 결과를 epN.json으로 저장한다."""
    if submission_number < 1:
        raise ValueError("submission_number는 1 이상이어야 합니다.")
    if not submission_text.strip():
        raise ValueError("submission_text가 비어 있습니다.")

    paths = StoryPaths(story_id, Path(data_root)) if data_root else StoryPaths(story_id)
    save_text(submission_text, paths.submission(submission_number))

    prompt = load_text(prompt_path)
    # prompt 첫 줄의 local ID namespace를 submission 번호에 맞춘다.
    # 예: chap = 1 -> chap = 7. local ID는 이후 ID split 단계에서 global ID로 변환된다.
    import re
    prompt = re.sub(r"(?m)^chap\s*=\s*\d+\s*$", f"chap = {submission_number}", prompt, count=1)
    caller = llm_callable or (lambda text, system: call_claude(text, system))
    response_text = caller(submission_text, prompt)
    ep = _parse_json_response(response_text)
    save_json(ep, paths.ep(submission_number))
    return ep
