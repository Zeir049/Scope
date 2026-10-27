"""분석 흐름 테스트 (2단계: 추출 → 검수 → 저장).

- 추출/검수 분리 정상 흐름 + 추출만 된 상태 save 거부
- 검수는 추출(extracted) 이후에만
- 누적 대조 모순(2화)
- 편의 analyze(추출+검수 연속)
- 각 단계 실패(extract/review) → failed + failed_stage
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.pipeline.interface import CanonDelta, ExtractionOutput, ReviewOutput
from tests.util import MANUAL_SAVE, poll_result

EXTRACTED = ("extracted", "failed")
FAILED = ("failed",)


# ── 파이프라인 테스트 더블 (단계별 실패 주입용) ──────────────────
class _ExtractBoom:
    """추출에서 실패하는 파이프라인."""

    async def extract_chapter(self, text, canon, title=None, *, chapter_no=None):  # noqa: ANN001
        raise RuntimeError("extract boom")

    async def review_chapter(self, text, canon, delta, title=None, *, chapter_no=None):  # noqa: ANN001
        return ReviewOutput()


class _ReviewBoom:
    """추출은 성공하고 검수에서 실패하는 파이프라인."""

    async def extract_chapter(self, text, canon, title=None, *, chapter_no=None):  # noqa: ANN001
        return ExtractionOutput(highlighted_text=text, canon_delta=CanonDelta())

    async def review_chapter(self, text, canon, delta, title=None, *, chapter_no=None):  # noqa: ANN001
        raise RuntimeError("review boom")


async def _upload(client: AsyncClient, pid: str, h: dict, no: int, text: str = "본문"):
    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": text}, headers=h
    )
    assert r.status_code == 201, r.text


# ── 정상 2단계 흐름 ──────────────────────────────────────────
async def test_extract_review_save_flow(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "나무꾼 이야기")

    # 아무것도 안 한 상태 저장 → 409
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 409

    # 1차 추출
    r = await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "extracting"

    res = await poll_result(client, pid, 1, h, stop=EXTRACTED)
    assert res["status"] == "extracted"
    assert res.get("canon_delta") is not None  # 추출 결과 존재
    assert res.get("contradictions") is None    # 아직 검수 전

    # 추출만 된 상태 저장 → 409 (검수 전엔 확정 불가)
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 409

    # 2차 검수
    r = await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "reviewing"

    res = await poll_result(client, pid, 1, h)  # 기본 stop = reviewed/saved/failed
    assert res["status"] == "reviewed"
    assert "highlighted_text" in res

    # 저장 → 캐논 병합
    r = await client.post(f"/projects/{pid}/chapters/1/save", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "saved"

    # 멱등 재저장
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200


async def test_review_requires_extraction(client: AsyncClient, auth_headers: dict, project_id: str):
    """추출(extracted) 전에 검수 요청 → 409."""
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1)
    r = await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert r.status_code == 409


async def test_contradiction_appears_after_canon(client: AsyncClient, auth_headers: dict, project_id: str):
    """1화 저장으로 캐논 생성 후, 2화 검수에서 모순이 검출된다."""
    h, pid = auth_headers, project_id

    # 1화: 추출 → 검수 → 저장
    await _upload(client, pid, h, 1, "첫 회차")
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    await poll_result(client, pid, 1, h, stop=EXTRACTED)
    await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    res1 = await poll_result(client, pid, 1, h)
    assert res1["status"] == "reviewed"
    assert not res1.get("contradictions")  # 기존 캐논 없음 → 모순 0
    await client.post(f"/projects/{pid}/chapters/1/save", headers=h)

    # 2화: 캐논 존재 → 모순 검출
    await _upload(client, pid, h, 2, "둘째 회차")
    await client.post(f"/projects/{pid}/chapters/2/extract", headers=h)
    await poll_result(client, pid, 2, h, stop=EXTRACTED)
    await client.post(f"/projects/{pid}/chapters/2/review", json=MANUAL_SAVE, headers=h)
    res2 = await poll_result(client, pid, 2, h)
    assert res2["status"] == "reviewed"
    assert res2.get("contradictions")
    c0 = res2["contradictions"][0]
    assert {"id", "span", "conflict_ref", "type"} <= c0.keys()


async def test_analyze_convenience_flow(client: AsyncClient, auth_headers: dict, project_id: str):
    """편의 analyze: 추출→검수를 한 번에 → reviewed → 저장."""
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "본문")

    r = await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "extracting"

    res = await poll_result(client, pid, 1, h)  # reviewed 까지 관찰
    assert res["status"] == "reviewed"

    r = await client.post(f"/projects/{pid}/chapters/1/save", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "saved"


# ── 단계별 실패 ──────────────────────────────────────────────
async def test_extract_failure(client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch):
    h, pid = auth_headers, project_id
    monkeypatch.setattr("app.workers.tasks.get_pipeline", lambda: _ExtractBoom())
    await _upload(client, pid, h, 1)

    r = await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    assert r.status_code == 202
    res = await poll_result(client, pid, 1, h, stop=FAILED)
    assert res["status"] == "failed"
    assert res.get("failed_stage") == "extract"


async def test_review_failure(client: AsyncClient, auth_headers: dict, project_id: str, monkeypatch):
    h, pid = auth_headers, project_id
    monkeypatch.setattr("app.workers.tasks.get_pipeline", lambda: _ReviewBoom())
    await _upload(client, pid, h, 1)

    # 추출은 성공
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)
    res = await poll_result(client, pid, 1, h, stop=EXTRACTED)
    assert res["status"] == "extracted"

    # 검수에서 실패
    await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    res = await poll_result(client, pid, 1, h, stop=FAILED)
    assert res["status"] == "failed"
    assert res.get("failed_stage") == "review"


async def test_result_missing_chapter_404(client: AsyncClient, auth_headers: dict, project_id: str):
    r = await client.get(f"/projects/{project_id}/chapters/99/result", headers=auth_headers)
    assert r.status_code == 404
