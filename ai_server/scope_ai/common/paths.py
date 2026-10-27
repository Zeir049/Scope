"""Story별 저장 경로를 한 곳에서 관리한다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = PROJECT_ROOT / "Data" / "stories"


@dataclass(frozen=True)
class StoryPaths:
    story_id: str
    data_root: Path = DEFAULT_DATA_ROOT

    @property
    def root(self) -> Path:
        return Path(self.data_root) / self.story_id

    @property
    def submissions_dir(self) -> Path:
        return self.root / "submissions"

    @property
    def episodes_dir(self) -> Path:
        return self.root / "episodes"

    @property
    def split_dir(self) -> Path:
        return self.root / "split"

    @property
    def embeddings_dir(self) -> Path:
        return self.root / "embeddings"

    @property
    def ers_dir(self) -> Path:
        return self.root / "ers"

    @property
    def reviews_dir(self) -> Path:
        return self.root / "reviews"

    def submission(self, number: int) -> Path:
        return self.submissions_dir / f"submission{number}.txt"

    def ep(self, number: int) -> Path:
        return self.episodes_dir / f"ep{number}.json"

    def ep_split_dir(self, number: int) -> Path:
        return self.split_dir / f"ep{number}"

    @property
    def ep_global(self) -> Path:
        return self.root / "ep_global.json"

    @property
    def event_embeddings(self) -> Path:
        return self.embeddings_dir / "event_embeddings.json"

    def ers_result(self, number: int) -> Path:
        return self.ers_dir / f"ers{number}.json"

    def review_result(self, number: int) -> Path:
        return self.reviews_dir / f"review{number}.json"
