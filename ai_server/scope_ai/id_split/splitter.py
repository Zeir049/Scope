"""epN.json을 field별 JSON으로 물리적으로 분리한다."""

from __future__ import annotations

from pathlib import Path

from ..common import EP_FIELDS, save_json, validate_ep


SPLIT_FILENAMES = {
    "worldview_rules": "worldview_rules.json",
    "characters": "characters.json",
    "events": "events.json",
    "times": "times.json",
    "locations": "locations.json",
}


def split_ep(ep: dict, output_dir: str | Path) -> dict[str, Path]:
    validate_ep(ep)
    output_dir = Path(output_dir)
    paths: dict[str, Path] = {}
    for field in EP_FIELDS:
        path = output_dir / SPLIT_FILENAMES[field]
        save_json(ep[field], path)
        paths[field] = path
    return paths
