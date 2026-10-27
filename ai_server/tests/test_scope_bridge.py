"""server/scope_bridge.py — 몸통 계약 ↔ scope_ai 변환 테스트.

LLM 은 가짜 함수로, 임베딩은 HashEmbedder 로 바꿔 비용·torch 없이 돈다.
    .venv\\Scripts\\python.exe -m unittest discover -s tests
"""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

import server.llm
from server import scope_bridge
from server.schemas import CanonSnapshot, ExtractRequest, ReviewRequest

CH1 = "유진은 아침에 교실 문을 열었다. 벨이 울렸기 때문이다."
CH2 = "다음 날 유진은 교실 문을 닫았다. 문이 열려 있었다."


def _ep(chap: int, text: str) -> dict:
    """analysis_prompt 의 출력 형식을 흉내 낸 1사건짜리 ep."""
    first_sentence = text.split(".")[0] + "."
    return {
        "worldview_rules": [
            {"rule_id": f"{chap}_RULE_000", "content": "교실 문은 벨이 울리면 연다", "source_text": first_sentence}
        ],
        "characters": [
            {"character_id": f"{chap}_CHAR_000", "name": "유진", "aliases": [], "traits": [], "relationships": []}
        ],
        "events": [
            {
                "event_id": f"{chap}_EVENT_000",
                "order": 1,
                "title": "유진이 문을 다룬다",
                "summary": first_sentence,
                "participant_character_ids": [f"{chap}_CHAR_000"],
                "main_actor_character_id": f"{chap}_CHAR_000",
                "time_id": f"{chap}_TIME_000",
                "location_id": f"{chap}_LOC_000",
                "cause": "벨이 울림",
                "result": "문 상태가 바뀜",
                "source_text": first_sentence,
            }
        ],
        "times": [
            {"time_id": f"{chap}_TIME_000", "event_id": f"{chap}_EVENT_000", "time_info": [4, 1], "offset": 1, "timeline_type": "main"}
        ],
        "locations": [
            {"location_id": f"{chap}_LOC_000", "event_id": f"{chap}_EVENT_000", "name": "교실", "location_info": [0, 0, 0, 0]}
        ],
    }


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, user_text: str, system_prompt: str) -> str:
        match = re.match(r"chap\s*=\s*(\d+)", system_prompt)
        if match:  # 1차 분석 프롬프트
            self.calls.append("analysis")
            return json.dumps(_ep(int(match.group(1)), user_text), ensure_ascii=False)
        self.calls.append("review")
        payload = json.loads(user_text.split("===== 신규 사건 및 ERS 관련 사건 =====\n", 1)[1])
        source = payload["events"][0]
        related = source["related"][0]["data"]["event"]["event_id"] if source["related"] else None
        return json.dumps(
            {
                "events": [
                    {
                        "source_event_id": source["source"]["event"]["event_id"],
                        "issues": [
                            {
                                "type": "time",
                                "severity": "conflict",
                                "related_event_id": related,
                                "description": "시간 순서가 어긋난다",
                                "evidence": ["1화는 아침", "2화는 다음 날"],
                            }
                        ],
                        "summary": "확인 필요",
                    }
                ]
            },
            ensure_ascii=False,
        )


def _run(coro):
    return asyncio.run(coro)


class ScopeBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self._saved = (scope_bridge.DATA_ROOT, scope_bridge.EMBEDDING_MODE, scope_bridge._embedder, server.llm.call_sync)
        scope_bridge.DATA_ROOT = Path(self.tmp.name)
        scope_bridge.EMBEDDING_MODE = "hash"
        scope_bridge._embedder = None
        server.llm.call_sync = self.llm
        self.canon = CanonSnapshot(project_id="proj-1", up_to_chapter=0)

    def tearDown(self) -> None:
        (scope_bridge.DATA_ROOT, scope_bridge.EMBEDDING_MODE, scope_bridge._embedder, server.llm.call_sync) = self._saved
        self.tmp.cleanup()

    def _extract(self, no: int, text: str, title: str | None = None) -> dict:
        return _run(scope_bridge.extract(ExtractRequest(chapter_text=text, canon=self.canon, title=title, chapter_no=no)))

    def _global(self) -> dict:
        return json.loads((Path(self.tmp.name) / "proj-1" / "ep_global.json").read_text(encoding="utf-8"))

    def test_extract_returns_global_ids_and_time_expression(self):
        visual = self._extract(1, CH1)
        self.assertEqual(visual["characters"][0]["character_id"], "CHAR_001")
        self.assertEqual(visual["events"][0]["event_id"], "EVENT_001")
        self.assertEqual(visual["events"][0]["participant_character_ids"], ["CHAR_001"])
        self.assertEqual(visual["events"][0]["time_id"], "TIME_001")
        self.assertEqual(visual["times"][0]["expression"], "직전 사건보다 약 하루 후")

        # 같은 이름의 인물은 다음 회차에서도 같은 global ID — 몸통 entity_key 가 이어진다.
        visual2 = self._extract(2, CH2)
        self.assertEqual(visual2["characters"][0]["character_id"], "CHAR_001")
        self.assertEqual(visual2["events"][0]["event_id"], "EVENT_002")

    def test_reextract_is_idempotent(self):
        self._extract(1, CH1)
        self._extract(2, CH2)
        self._extract(2, CH2)
        global_ep = self._global()
        self.assertEqual(len(global_ep["events"]), 2)
        self.assertEqual(len(global_ep["characters"]), 1)
        self.assertEqual(global_ep["characters"][0]["source_submissions"], [1, 2])
        self.assertEqual([e["event_id"] for e in global_ep["events"]], ["EVENT_001", "EVENT_002"])

    def test_rule_document_prefix_goes_to_llm_only(self):
        seen = []
        server.llm.call_sync = lambda user, system: seen.append(user) or self.llm(user, system)
        self._extract(1, CH1, title="[규칙] 설정")
        self.assertTrue(seen[0].startswith("[아래 본문은 서사가 아니라"))
        saved = (Path(self.tmp.name) / "proj-1" / "submissions" / "submission1.txt").read_text(encoding="utf-8")
        self.assertEqual(saved, CH1)

    def test_review_maps_issues_to_contradictions(self):
        self._extract(1, CH1)
        self._extract(2, CH2)
        out = _run(scope_bridge.review(ReviewRequest(chapter_text=CH2, canon=self.canon, chapter_no=2)))
        self.assertEqual(len(out.contradictions), 1)
        c = out.contradictions[0]
        self.assertEqual(c.type, "timeline")
        self.assertEqual(c.confidence, 0.9)
        self.assertEqual(c.conflict_ref.chapter_no, 1)
        self.assertEqual(CH2[c.span.start : c.span.end], "다음 날 유진은 교실 문을 닫았다.")
        self.assertIn("근거: 1화는 아침 / 2화는 다음 날", c.explanation)

    def test_review_without_extract_backfills_and_embeds_previous_chapters(self):
        self._extract(1, CH1)  # 1화는 추출만 하고 검수 없이 지나감 → 임베딩 없음
        _run(scope_bridge.review(ReviewRequest(chapter_text=CH2, canon=self.canon, chapter_no=2)))
        self.assertEqual(self.llm.calls, ["analysis", "analysis", "review"])
        store = json.loads((Path(self.tmp.name) / "proj-1" / "embeddings" / "event_embeddings.json").read_text(encoding="utf-8"))
        self.assertEqual(store["model"], "hash-2gram-256")
        self.assertEqual({e["event_id"] for e in store["events"]}, {"EVENT_001", "EVENT_002"})

    def test_chapter_no_falls_back_to_up_to_chapter(self):
        canon = CanonSnapshot(project_id="proj-1", up_to_chapter=3)
        self.assertEqual(scope_bridge.chapter_no_of(ExtractRequest(chapter_text="x", canon=canon)), 4)

    def test_unparseable_review_is_502(self):
        self._extract(1, CH1)
        self._extract(2, CH2)
        server.llm.call_sync = lambda user, system: self.llm(user, system) if system.startswith("chap") else "not json"
        with self.assertRaises(Exception) as ctx:
            _run(scope_bridge.review(ReviewRequest(chapter_text=CH2, canon=self.canon, chapter_no=2)))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 502)


if __name__ == "__main__":
    unittest.main()
