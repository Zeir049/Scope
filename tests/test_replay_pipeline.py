"""시연용 ReplayPipeline (PIPELINE_MODE=replay).

- 단위: 1~3화 자료가 복선을 뺀 6종을 모두 채우고, 모순 인용이 업로드 원문 안에 있는지.
- API: 실제 업로드 → 추출 → 검수 → 저장을 1→2→3화로 돌려, 회차별 시각화(canon chapter=N)가
  모든 탭에서 비지 않는지와 인물 버전이 쌓이는지 본다.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.pipeline.interface import CanonSnapshot
from app.pipeline.replay import REPLAY_DIR, ReplayPipeline
from tests.util import MANUAL_SAVE, poll_result

CHAPTERS = (1, 2, 3)
DELTA_FIELDS = ("worldview", "characters", "relations", "timeline", "spaces", "events")


def _text(n: int) -> str:
    return (REPLAY_DIR / f"chapter_{n}.txt").read_text(encoding="utf-8")


def _canon() -> CanonSnapshot:
    return CanonSnapshot(project_id="p")


@pytest.mark.parametrize("n", CHAPTERS)
async def test_extract_fills_every_category_but_foreshadowing(n: int) -> None:
    out = await ReplayPipeline().extract_chapter(_text(n), _canon(), chapter_no=n)
    for field in DELTA_FIELDS:
        assert getattr(out.canon_delta, field), f"{n}화 {field} 비어 있음"
    assert out.canon_delta.foreshadowing == []  # AI 결과에 복선이 없다
    assert out.visual_json and out.highlighted_text == _text(n)
    assert all(t.time_value for t in out.canon_delta.timeline)


async def test_review_quotes_come_from_uploaded_text() -> None:
    pipe = ReplayPipeline()
    assert (await pipe.review_chapter(_text(1), _canon(), None, chapter_no=1)).contradictions == []
    for n in (2, 3):
        text = _text(n)
        out = await pipe.review_chapter(text, _canon(), None, chapter_no=n)
        assert out.contradictions
        for c in out.contradictions:
            assert text[c.span.start : c.span.end] == c.span.quote
            assert c.conflict_ref.chapter_no is None or 1 <= c.conflict_ref.chapter_no <= n
            assert "PLANT_" not in c.explanation
            assert "유형 목록" not in c.explanation and "(order " not in c.explanation  # 평가용 메모


async def test_unknown_chapter_fails_loudly() -> None:
    with pytest.raises(ValueError, match="리플레이 자료가 없는 회차"):
        await ReplayPipeline().extract_chapter("본문", _canon(), chapter_no=9)


async def test_health_lists_chapters() -> None:
    h = await ReplayPipeline().health()
    assert h.ok and h.mode == "replay" and "[1, 2, 3]" in h.message


async def _save(client: AsyncClient, pid: str, h: dict, n: int) -> None:
    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": n, "text": _text(n)}, headers=h
    )
    assert r.status_code == 201, r.text
    await client.post(f"/projects/{pid}/chapters/{n}/extract", headers=h)
    assert (await poll_result(client, pid, n, h, stop=("extracted", "failed")))["status"] == "extracted"
    await client.post(f"/projects/{pid}/chapters/{n}/review", json=MANUAL_SAVE, headers=h)
    res = await poll_result(client, pid, n, h)
    assert res["status"] == "reviewed"
    assert bool(res["contradictions"]) == (n > 1)
    assert (await client.post(f"/projects/{pid}/chapters/{n}/save", headers=h)).status_code == 200


async def test_every_tab_has_chapter_contribution(
    client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch
) -> None:
    from app.workers import tasks

    pipe = ReplayPipeline()
    monkeypatch.setattr(tasks, "get_pipeline", lambda: pipe)
    h, pid = auth_headers, project_id
    for n in CHAPTERS:
        await _save(client, pid, h, n)

    for n in CHAPTERS:
        for view in ("worldview", "timeline", "spaces", "events"):
            r = await client.get(f"/projects/{pid}/canon", params={"view": view, "chapter": n}, headers=h)
            assert r.json()["items"], f"{n}화 {view} 기여 없음"
        chars = (
            await client.get(f"/projects/{pid}/canon", params={"view": "characters", "chapter": n}, headers=h)
        ).json()
        assert chars["nodes"] and chars["edges"], f"{n}화 인물 기여 없음"

    # 특징이 회차마다 누적돼 코브는 3화에서 버전 3
    current = (await client.get(f"/projects/{pid}/canon", params={"view": "characters"}, headers=h)).json()
    cobb = next(node for node in current["nodes"] if node["entity_key"] == "CHAR_001")
    assert cobb["version"] == 3 and cobb["source_chapter"] == 3
