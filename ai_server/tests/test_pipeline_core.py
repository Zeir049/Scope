from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scope_ai.common import StoryPaths, save_json, save_text, load_json
from scope_ai.id_split import process_ep
from scope_ai.embedding.base import BaseEmbedder
from scope_ai.embedding.service import embed_submission_events
from scope_ai.ers.ranking import rank_related_events


class FakeEmbedder(BaseEmbedder):
    model_name = "fake"

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            # deterministic 3D vector; sufficient for pipeline tests
            a = float(len(text) % 7 + 1)
            b = float(sum(ord(c) for c in text) % 11 + 1)
            c = 1.0
            norm = (a*a + b*b + c*c) ** 0.5
            result.append([a/norm, b/norm, c/norm])
        return result


def make_ep(chap: int, name: str, title: str, summary: str, cause: str, result: str):
    return {
        "worldview_rules": [],
        "characters": [
            {
                "character_id": f"{chap}_CHAR_001",
                "name": name,
                "aliases": [],
            }
        ],
        "events": [
            {
                "event_id": f"{chap}_EVENT_001",
                "order": 1,
                "title": title,
                "summary": summary,
                "participant_character_ids": [f"{chap}_CHAR_001"],
                "main_actor_character_id": f"{chap}_CHAR_001",
                "time_id": f"{chap}_TIME_001",
                "location_id": f"{chap}_LOC_001",
                "cause": cause,
                "result": result,
            }
        ],
        "times": [
            {
                "time_id": f"{chap}_TIME_001",
                "event_id": f"{chap}_EVENT_001",
                "time_info": [0, 0],
                "offset": 1,
            }
        ],
        "locations": [
            {
                "location_id": f"{chap}_LOC_001",
                "event_id": f"{chap}_EVENT_001",
                "name": "교실",
                "location_info": [0, 0, 0, 0],
            }
        ],
    }


class PipelineCoreTest(unittest.TestCase):
    def test_incremental_split_embedding_and_ers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = StoryPaths("story_a", root)

            ep1 = make_ep(1, "유진", "문을 연다", "유진이 문을 연다", "벨이 울림", "문이 열림")
            save_json(ep1, paths.ep(1))
            save_text("첫 원문", paths.submission(1))
            process_ep("story_a", 1, data_root=root)
            embed_submission_events("story_a", 1, data_root=root, embedder=FakeEmbedder())

            ep2 = make_ep(2, "유진", "문을 닫는다", "유진이 다시 문을 닫는다", "문이 열려 있음", "문이 닫힘")
            save_json(ep2, paths.ep(2))
            save_text("둘째 원문", paths.submission(2))
            split_result = process_ep("story_a", 2, data_root=root)
            self.assertEqual(split_result["id_maps"]["characters"]["2_CHAR_001"], "CHAR_001")

            global_ep = load_json(paths.ep_global)
            self.assertEqual(len(global_ep["characters"]), 1)
            self.assertEqual(len(global_ep["events"]), 2)

            embed_submission_events("story_a", 2, data_root=root, embedder=FakeEmbedder())
            ers = rank_related_events("story_a", 2, top_k=1, data_root=root)
            self.assertEqual(ers["events"][0]["top_k"][0]["event_id"], "EVENT_001")
            self.assertIn("features", ers["events"][0]["top_k"][0])
            self.assertIsNone(ers["events"][0]["top_k"][0]["features"]["time"])
            self.assertIsNone(ers["events"][0]["top_k"][0]["features"]["location"])


if __name__ == "__main__":
    unittest.main()
