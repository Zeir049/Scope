"""2단계: epN 분할 → 타입별 ID 통합 → ep_global 갱신."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ..common import StoryPaths, empty_ep, load_json, save_json, validate_ep
from .splitter import split_ep
from .character_manager import plan_character_ids, merge_characters
from .rule_manager import plan_rule_ids, merge_rules
from .event_manager import plan_event_ids, merge_events
from .time_manager import plan_time_ids, merge_times
from .location_manager import plan_location_ids, merge_locations
from .reference_mapper import replace_references


def process_ep(
    story_id: str,
    submission_number: int,
    *,
    ep: dict | None = None,
    data_root: str | Path | None = None,
) -> dict:
    if submission_number < 1:
        raise ValueError("submission_number는 1 이상이어야 합니다.")

    paths = StoryPaths(story_id, Path(data_root)) if data_root else StoryPaths(story_id)
    current = deepcopy(ep) if ep is not None else load_json(paths.ep(submission_number))
    validate_ep(current)

    # ID 통합 전에 ep를 field별 파일로 먼저 보존한다.
    split_ep(current, paths.ep_split_dir(submission_number))

    global_ep = load_json(paths.ep_global) if paths.ep_global.exists() else empty_ep()
    validate_ep(global_ep)

    character_map = plan_character_ids(current["characters"], global_ep["characters"])
    rule_map = plan_rule_ids(current["worldview_rules"], global_ep["worldview_rules"])
    event_map = plan_event_ids(current["events"], global_ep["events"])
    time_map = plan_time_ids(current["times"], global_ep["times"])
    location_map = plan_location_ids(current["locations"], global_ep["locations"])

    mappings = [character_map, rule_map, event_map, time_map, location_map]
    transformed = {
        field: replace_references(current[field], mappings)
        for field in current
        if field in {"worldview_rules", "characters", "events", "times", "locations"}
    }

    # 디버깅/역추적을 위해 원래 local ID를 각 새 객체에 남긴다.
    id_fields = {
        "worldview_rules": "rule_id",
        "characters": "character_id",
        "events": "event_id",
        "times": "time_id",
        "locations": "location_id",
    }
    for field, id_field in id_fields.items():
        for original, mapped in zip(current[field], transformed[field]):
            if original.get(id_field):
                mapped["source_local_id"] = original[id_field]

    global_ep["characters"] = merge_characters(
        transformed["characters"], global_ep["characters"], submission_number
    )
    global_ep["worldview_rules"] = merge_rules(
        transformed["worldview_rules"], global_ep["worldview_rules"], submission_number
    )
    global_ep["events"] = merge_events(
        transformed["events"], global_ep["events"], submission_number
    )
    global_ep["times"] = merge_times(
        transformed["times"], global_ep["times"], submission_number
    )
    global_ep["locations"] = merge_locations(
        transformed["locations"], global_ep["locations"], submission_number
    )

    save_json(global_ep, paths.ep_global)

    return {
        "submission_number": submission_number,
        "ep_global_path": str(paths.ep_global),
        "id_maps": {
            "characters": character_map,
            "worldview_rules": rule_map,
            "events": event_map,
            "times": time_map,
            "locations": location_map,
        },
        "new_event_ids": list(event_map.values()),
        "counts": {field: len(current[field]) for field in current if isinstance(current[field], list)},
    }
