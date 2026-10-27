"""시각화 원본 JSON(prompt_result_1 포맷) 경로 테스트.

- transform: rich JSON → CanonDelta 매핑 (순수 단위 테스트)
- 파이프라인이 rich JSON을 주면 raw_output에 보존 → GET visual 로 원본 조회
- fake 파이프라인(visual 없음)이면 visual=null
- 미존재 회차 → 404
"""
from __future__ import annotations

from httpx import AsyncClient

from app.pipeline.interface import ExtractionOutput, ReviewOutput
from app.pipeline.transform import looks_like_visual_json, visual_to_canon_delta
from tests.util import poll_result

SAMPLE_VISUAL = {
    "worldview_rules": [
        {
            "rule_id": "RULE_001",
            "content": "소마를 통한 평온 유지",
            "description": "소마로 평온한 상태를 유지한다.",
            "source_text": "'소마'를 통해서 평온한 상태를 유지하고 있습니다.",
            "certainty": "explicit",
        }
    ],
    "characters": [
        {
            "character_id": "CHAR_001",
            "name": "클라인",
            "aliases": ["Klein Bruder"],
            "description": "헤일트라움의 가이드",
            "traits": [{"trait": "단정한 말투", "trait_type": "personality"}],
            "relationships": [
                {
                    "target_character_id": "CHAR_002",
                    "relationship_type": "unknown",
                    "description": "임무를 부여한다",
                }
            ],
        },
        {"character_id": "CHAR_002", "name": "플레이어", "aliases": [], "traits": [], "relationships": []},
    ],
    "events": [{"event_id": "EVENT_001", "order": 1, "title": "정책 회의"}],
    "times": [{"time_id": "TIME_001", "expression": "목요일 점심 전"}],
    "locations": [{"location_id": "LOC_001", "name": "회의실", "description": "회빛의 방"}],
}


# ── 변환 단위 테스트 ──────────────────────────────────────────
def test_transform_maps_visual_to_delta():
    assert looks_like_visual_json(SAMPLE_VISUAL)
    delta = visual_to_canon_delta(SAMPLE_VISUAL)

    assert [w.entity_key for w in delta.worldview] == ["RULE_001"]
    assert delta.worldview[0].item == "소마를 통한 평온 유지"
    assert delta.worldview[0].detail == "소마로 평온한 상태를 유지한다."

    assert {c.entity_key for c in delta.characters} == {"CHAR_001", "CHAR_002"}
    klein = next(c for c in delta.characters if c.entity_key == "CHAR_001")
    # traits 는 {trait, trait_type, certainty} 객체(키 3개 고정) — 원본의 trait_type 을 버리지 않는다
    assert klein.attrs["traits"] == [
        {"trait": "단정한 말투", "trait_type": "personality", "certainty": None}
    ]
    assert klein.attrs["aliases"] == ["Klein Bruder"]

    assert delta.relations[0].entity_key == "CHAR_001->CHAR_002"
    assert delta.relations[0].from_char == "CHAR_001"

    assert delta.events[0].label == "정책 회의" and delta.events[0].order_index == 1
    assert delta.timeline[0].time_value == "목요일 점심 전"
    assert delta.spaces[0].place == "회의실"


def test_extraction_output_is_not_visual_json():
    assert not looks_like_visual_json({"highlighted_text": "", "canon_delta": {}})


# ── rich JSON을 주는 파이프라인 더블 ─────────────────────────
class _RichPipeline:
    async def extract_chapter(self, text, canon, title=None, *, chapter_no=None):  # noqa: ANN001
        return ExtractionOutput(
            highlighted_text=text,
            canon_delta=visual_to_canon_delta(SAMPLE_VISUAL),
            visual_json=SAMPLE_VISUAL,
        )

    async def review_chapter(self, text, canon, delta, title=None, *, chapter_no=None):  # noqa: ANN001
        return ReviewOutput()


async def test_visual_roundtrip(client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch):
    """rich 파이프라인 → raw_output 보존 → GET visual 로 원본 그대로, 캐논 병합까지."""
    monkeypatch.setattr("app.workers.tasks.get_pipeline", lambda: _RichPipeline())
    h, pid = auth_headers, project_id

    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h
    )
    assert r.status_code == 201, r.text
    assert (await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)).status_code == 202
    res = await poll_result(client, pid, 1, h)
    assert res["status"] == "reviewed"

    r = await client.get(f"/projects/{pid}/chapters/1/visual", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chapter_no"] == 1
    assert body["visual"] == SAMPLE_VISUAL

    # 변환된 델타가 캐논 병합까지 정상 동작하는지
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200
    r = await client.get(f"/projects/{pid}/canon", params={"view": "worldview"}, headers=h)
    assert any(i["item"] == "소마를 통한 평온 유지" for i in r.json()["items"])


async def test_fake_pipeline_returns_sample_visual(client: AsyncClient, auth_headers: dict, project_id: str):
    """기본 fake 파이프라인: 일반 회차는 헤일트라움 샘플 visual을 그대로 내려준다."""
    h, pid = auth_headers, project_id
    await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h
    )
    await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)
    await poll_result(client, pid, 1, h)

    r = await client.get(f"/projects/{pid}/chapters/1/visual", headers=h)
    assert r.status_code == 200
    visual = r.json()["visual"]
    assert visual and "worldview_rules" in visual
    assert any(rule["rule_id"] == "RULE_001" for rule in visual["worldview_rules"])


async def test_visual_null_for_rules_chapter(client: AsyncClient, auth_headers: dict, project_id: str):
    """[규칙] 회차는 사용자 문서 그대로라 visual이 없다(null) — 프론트는 데모 폴백."""
    h, pid = auth_headers, project_id
    await client.post(
        f"/projects/{pid}/chapters",
        json={"chapter_no": 1, "title": "[규칙] 세계관.txt", "text": "- 마법은 밤에만 쓸 수 있다"},
        headers=h,
    )
    await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)
    await poll_result(client, pid, 1, h)

    r = await client.get(f"/projects/{pid}/chapters/1/visual", headers=h)
    assert r.status_code == 200 and r.json()["visual"] is None


async def test_visual_missing_chapter_404(client: AsyncClient, auth_headers: dict, project_id: str):
    r = await client.get(f"/projects/{project_id}/chapters/99/visual", headers=auth_headers)
    assert r.status_code == 404
