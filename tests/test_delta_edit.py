"""추출 결과 항목 편집 테스트 (extracted 상태에서 canon_delta JSON 수정/삭제/추가).

- 정상 수정/삭제/추가
- 권한 위반(403), 미존재 항목(404), 잘못된 category(400), 본문 검증(400), 중복 추가(409)
- saved 상태 편집 거부(409)
- 편집 후 save 시 편집본이 캐논에 반영(추가 항목 존재 / 삭제 항목 부재)
"""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.util import MANUAL_SAVE, poll_result

EXTRACTED = ("extracted", "failed")


async def _extract(client: AsyncClient, pid: str, h: dict, no: int = 1) -> dict:
    r = await client.post(
        # 회차마다 본문을 다르게 — 같은 원문은 중복 업로드로 409(D3)
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": f"본문 {no}"}, headers=h
    )
    assert r.status_code == 201, r.text
    await client.post(f"/projects/{pid}/chapters/{no}/extract", headers=h)
    res = await poll_result(client, pid, no, h, stop=EXTRACTED)
    assert res["status"] == "extracted"
    return res


def _wv_keys(result: dict) -> list[str]:
    return [x["entity_key"] for x in result["canon_delta"]["worldview"]]


async def _result(client: AsyncClient, pid: str, h: dict, no: int = 1) -> dict:
    return (await client.get(f"/projects/{pid}/chapters/{no}/result", headers=h)).json()


# ── 정상 흐름 ────────────────────────────────────────────────
async def test_update_delta_item(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)
    body = {"entity_key": "RULE_001", "item": "소마 배급이 중단되었다", "detail": "수정됨"}
    r = await client.patch(f"/projects/{pid}/chapters/1/delta/worldview/RULE_001", json=body, headers=h)
    assert r.status_code == 200 and r.json()["item"] == "소마 배급이 중단되었다"

    wl = (await _result(client, pid, h))["canon_delta"]["worldview"]
    cur = next(x for x in wl if x["entity_key"] == "RULE_001")
    assert cur["item"] == "소마 배급이 중단되었다" and cur["detail"] == "수정됨"


async def test_add_delta_item(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)
    body = {"entity_key": "magic", "item": "마법이 존재한다"}
    r = await client.post(f"/projects/{pid}/chapters/1/delta/worldview", json=body, headers=h)
    assert r.status_code == 201 and r.json()["entity_key"] == "magic"
    assert "magic" in _wv_keys(await _result(client, pid, h))

    # 같은 entity_key 중복 추가 → 409
    r2 = await client.post(f"/projects/{pid}/chapters/1/delta/worldview", json=body, headers=h)
    assert r2.status_code == 409


async def test_delete_delta_item(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)
    r = await client.delete(f"/projects/{pid}/chapters/1/delta/worldview/RULE_002", headers=h)
    assert r.status_code == 204
    assert "RULE_002" not in _wv_keys(await _result(client, pid, h))


# ── 오류 케이스 ──────────────────────────────────────────────
async def test_edit_errors(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)

    # 없는 entity_key → 404 (PATCH/DELETE)
    r = await client.patch(
        f"/projects/{pid}/chapters/1/delta/worldview/nope",
        json={"entity_key": "nope", "item": "x"}, headers=h,
    )
    assert r.status_code == 404
    assert (await client.delete(f"/projects/{pid}/chapters/1/delta/worldview/nope", headers=h)).status_code == 404

    # 잘못된 category → 400
    r = await client.post(f"/projects/{pid}/chapters/1/delta/bogus", json={"entity_key": "a", "item": "b"}, headers=h)
    assert r.status_code == 400

    # 본문 검증 실패(worldview는 item 필수) → 400
    r = await client.post(f"/projects/{pid}/chapters/1/delta/worldview", json={"entity_key": "a"}, headers=h)
    assert r.status_code == 400

    # 경로/본문 entity_key 불일치 → 400
    r = await client.patch(
        f"/projects/{pid}/chapters/1/delta/worldview/RULE_001",
        json={"entity_key": "other", "item": "x"}, headers=h,
    )
    assert r.status_code == 400


async def test_edit_requires_ownership(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = await client.delete(f"/projects/{pid}/chapters/1/delta/worldview/RULE_001", headers=h2)
    assert r.status_code == 403


async def test_edit_denied_after_saved(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)
    await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200

    # saved 이후 편집 → 409
    r = await client.delete(f"/projects/{pid}/chapters/1/delta/worldview/RULE_001", headers=h)
    assert r.status_code == 409
    r = await client.post(f"/projects/{pid}/chapters/1/delta/worldview", json={"entity_key": "z", "item": "z"}, headers=h)
    assert r.status_code == 409


# ── 편집본이 저장 시 캐논에 반영 ─────────────────────────────
async def test_edited_delta_reflected_in_canon(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _extract(client, pid, h)

    # 추가 + 삭제
    await client.post(f"/projects/{pid}/chapters/1/delta/worldview", json={"entity_key": "magic", "item": "마법이 존재한다"}, headers=h)
    await client.delete(f"/projects/{pid}/chapters/1/delta/worldview/RULE_002", headers=h)

    # 검수 → 저장
    await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200

    # 캐논(worldview) 확인: 추가 항목 존재, 삭제 항목 부재, 기존 RULE_001 유지
    b = (await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)).json()
    items = [it["item"] for it in b["items"]]
    assert "마법이 존재한다" in items
    assert "설계된 수명 단축 정책" not in items  # RULE_002 삭제됨
    assert "소마(Soma)를 통한 평온 유지 시스템" in items


# ── reviewed 상태 편집 → extracted 회귀 + 낡은 모순 제거 → 재검수 → 저장 ──
async def test_edit_in_reviewed_regresses_to_extracted(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id

    # 1화 저장으로 캐논 생성(이후 2화 검수에서 모순이 나오도록)
    await _extract(client, pid, h, 1)
    await client.post(f"/projects/{pid}/chapters/1/review", json=MANUAL_SAVE, headers=h)
    assert (await poll_result(client, pid, 1, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/1/save", headers=h)).status_code == 200

    # 2화: 추출 → 검수 → reviewed (캐논이 있으니 모순 검출)
    await _extract(client, pid, h, 2)
    await client.post(f"/projects/{pid}/chapters/2/review", json=MANUAL_SAVE, headers=h)
    res = await poll_result(client, pid, 2, h)
    assert res["status"] == "reviewed"
    assert res.get("contradictions")  # 모순 존재

    # reviewed 상태에서 편집 → extracted 회귀 + 기존 모순 제거 + 편집 반영
    r = await client.post(
        f"/projects/{pid}/chapters/2/delta/worldview",
        json={"entity_key": "extra", "item": "추가 설정"}, headers=h,
    )
    assert r.status_code == 201
    res2 = await _result(client, pid, h, 2)
    assert res2["status"] == "extracted"          # 상태 회귀
    assert not res2.get("contradictions")          # 낡은 모순 제거
    assert "extra" in _wv_keys(res2)               # 편집 반영

    # 재검수 → reviewed → 저장(편집본 기준)
    assert (await client.post(f"/projects/{pid}/chapters/2/review", json=MANUAL_SAVE, headers=h)).status_code == 202
    assert (await poll_result(client, pid, 2, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/2/save", headers=h)).status_code == 200

    # 편집 항목이 캐논에 반영
    b = (await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)).json()
    assert "추가 설정" in [it["item"] for it in b["items"]]
