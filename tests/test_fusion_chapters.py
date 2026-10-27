"""융합 1단계 — 회차 상세 / 종류(kind) / 삭제 / 중복 업로드 거절(D3)."""
from __future__ import annotations

import hashlib
import uuid

from httpx import AsyncClient

from app.workers.tasks import _record_failure
from tests.util import MANUAL_SAVE, poll_result


async def _register(client: AsyncClient) -> dict[str, str]:
    sfx = uuid.uuid4().hex[:8]
    r = await client.post(
        "/auth/register",
        json={"email": f"fc_{sfx}@x.com", "password": "secret123", "name": "Other"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _upload(client: AsyncClient, pid: str, h: dict, no: int, text: str, **extra):
    return await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": text, **extra}, headers=h
    )


async def _save_chain(client: AsyncClient, pid: str, h: dict, no: int) -> None:
    await client.post(f"/projects/{pid}/chapters/{no}/extract", headers=h)
    assert (await poll_result(client, pid, no, h, stop=("extracted", "failed")))["status"] == "extracted"
    await client.post(f"/projects/{pid}/chapters/{no}/review", json=MANUAL_SAVE, headers=h)
    assert (await poll_result(client, pid, no, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/{no}/save", headers=h)).status_code == 200


# ── 상세 ────────────────────────────────────────────────────
async def test_chapter_detail(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    text = "1화 원문입니다."
    assert (await _upload(client, pid, h, 1, text, title="첫 화")).status_code == 201

    r = await client.get(f"/projects/{pid}/chapters/1", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["chapter_no"] == 1 and d["title"] == "첫 화"
    assert d["kind"] == "narrative" and d["status"] == "uploaded"
    assert d["raw_text"] == text
    assert d["content_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert d["created_at"] and d["updated_at"]
    assert d["failed_stage"] is None and d["failed_detail"] is None
    assert d["contradiction_count"] == 0

    # 목록에는 kind/updated_at 이 추가되고 원문은 없다
    item = (await client.get(f"/projects/{pid}/chapters", headers=h)).json()["items"][0]
    assert item["kind"] == "narrative" and item["updated_at"]
    assert "raw_text" not in item


async def test_chapter_detail_failed_and_contradictions(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "1화")
    await _save_chain(client, pid, h, 1)
    await _upload(client, pid, h, 2, "2화")
    await client.post(f"/projects/{pid}/chapters/2/extract", headers=h)
    await poll_result(client, pid, 2, h, stop=("extracted",))
    await client.post(f"/projects/{pid}/chapters/2/review", json=MANUAL_SAVE, headers=h)
    await poll_result(client, pid, 2, h)
    d = (await client.get(f"/projects/{pid}/chapters/2", headers=h)).json()
    assert d["contradiction_count"] >= 1  # 캐논이 있으니 FakePipeline 이 모순을 낸다

    await _upload(client, pid, h, 3, "3화")
    await _record_failure(uuid.UUID(pid), 3, "extract", "boom")
    d = (await client.get(f"/projects/{pid}/chapters/3", headers=h)).json()
    assert d["status"] == "failed"
    assert d["failed_stage"] == "extract" and d["failed_detail"] == "boom"


async def test_chapter_detail_forbidden_and_missing(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    await _upload(client, project_id, auth_headers, 1, "본문")
    other = await _register(client)
    assert (await client.get(f"/projects/{project_id}/chapters/1", headers=other)).status_code == 403
    assert (await client.get(f"/projects/{project_id}/chapters/99", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/projects/{uuid.uuid4()}/chapters/1", headers=auth_headers)).status_code == 404


# ── 종류(kind) ───────────────────────────────────────────────
async def test_kind_json_multipart_and_put(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    r = await _upload(client, pid, h, 1, "- 마법은 없다", kind="rules")
    assert r.status_code == 201 and r.json()["kind"] == "rules"

    r = await client.post(
        f"/projects/{pid}/chapters",
        data={"chapter_no": "2", "kind": "rules"},
        files={"file": ("rules.txt", "- 밤에는 성문을 닫는다".encode("utf-8"), "text/plain")},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["kind"] == "rules"

    # PUT: kind 생략 → 유지, 지정 → 변경
    r = await client.put(f"/projects/{pid}/chapters/1", json={"text": "- 마법은 있다"}, headers=h)
    assert r.json()["kind"] == "rules"
    r = await client.put(
        f"/projects/{pid}/chapters/1", json={"text": "평범한 서사", "kind": "narrative"}, headers=h
    )
    assert r.json()["kind"] == "narrative"
    assert (await client.get(f"/projects/{pid}/chapters/1", headers=h)).json()["kind"] == "narrative"


async def test_kind_invalid_is_400(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    r = await _upload(client, pid, h, 1, "본문", kind="poem")
    assert r.status_code == 400 and "종류" in r.json()["detail"]
    r = await client.post(
        f"/projects/{pid}/chapters",
        data={"chapter_no": "1", "kind": "poem"},
        files={"file": ("a.txt", "본문".encode("utf-8"), "text/plain")},
        headers=h,
    )
    assert r.status_code == 400
    await _upload(client, pid, h, 1, "본문")
    r = await client.put(f"/projects/{pid}/chapters/1", json={"text": "새 본문", "kind": "poem"}, headers=h)
    assert r.status_code == 400


# ── 삭제 ─────────────────────────────────────────────────────
async def test_delete_chapter(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "본문")
    r = await client.delete(f"/projects/{pid}/chapters/1", headers=h)
    assert r.status_code == 204
    assert (await client.get(f"/projects/{pid}/chapters/1", headers=h)).status_code == 404
    # 지운 뒤 같은 원문을 다시 올릴 수 있다(해시도 함께 사라짐)
    assert (await _upload(client, pid, h, 1, "본문")).status_code == 201


async def test_delete_with_analysis_rows_cascades(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "1화")
    await _save_chain(client, pid, h, 1)
    await _upload(client, pid, h, 2, "2화")
    await client.post(f"/projects/{pid}/chapters/2/extract", headers=h)
    await poll_result(client, pid, 2, h, stop=("extracted",))
    await client.post(f"/projects/{pid}/chapters/2/review", json=MANUAL_SAVE, headers=h)
    await poll_result(client, pid, 2, h)  # reviewed + 모순 있음
    assert (await client.delete(f"/projects/{pid}/chapters/2", headers=h)).status_code == 204


async def test_delete_saved_is_409(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "본문")
    await _save_chain(client, pid, h, 1)
    r = await client.delete(f"/projects/{pid}/chapters/1", headers=h)
    assert r.status_code == 409
    assert "저장된 회차는 삭제할 수 없습니다" in r.json()["detail"]


async def test_delete_in_progress_is_409(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "본문")
    await client.post(f"/projects/{pid}/chapters/1/extract", headers=h)  # FakePipeline 1초 지연
    r = await client.delete(f"/projects/{pid}/chapters/1", headers=h)
    assert r.status_code == 409
    await poll_result(client, pid, 1, h, stop=("extracted", "failed"))  # 백그라운드 작업 정리


async def test_delete_forbidden_and_missing(client: AsyncClient, auth_headers: dict, project_id: str):
    await _upload(client, project_id, auth_headers, 1, "본문")
    other = await _register(client)
    assert (await client.delete(f"/projects/{project_id}/chapters/1", headers=other)).status_code == 403
    assert (await client.delete(f"/projects/{project_id}/chapters/99", headers=auth_headers)).status_code == 404


# ── 중복 업로드 (D3) ─────────────────────────────────────────
async def test_duplicate_upload_rejected_with_existing_no(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "똑같은 원고")
    r = await _upload(client, pid, h, 2, "똑같은 원고")
    assert r.status_code == 409
    body = r.json()
    assert body["existing_chapter_no"] == 1
    assert "1화" in body["detail"]
    assert (await client.get(f"/projects/{pid}/chapters/2", headers=h)).status_code == 404

    # multipart(파일)도 파싱된 원문 기준으로 같은 판단
    r = await client.post(
        f"/projects/{pid}/chapters",
        data={"chapter_no": "3"},
        files={"file": ("dup.txt", "똑같은 원고".encode("utf-8"), "text/plain")},
        headers=h,
    )
    assert r.status_code == 409 and r.json()["existing_chapter_no"] == 1


async def test_duplicate_is_project_scoped(client: AsyncClient, auth_headers: dict, project_id: str):
    h = auth_headers
    await _upload(client, project_id, h, 1, "원고")
    other_pid = (await client.post("/projects", json={"name": "다른 작품"}, headers=h)).json()["id"]
    assert (await _upload(client, other_pid, h, 1, "원고")).status_code == 201


async def test_reupload_with_same_text_passes_and_updates_hash(
    client: AsyncClient, auth_headers: dict, project_id: str
):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1, "1화 원고")
    await _upload(client, pid, h, 2, "2화 원고")
    r = await client.put(f"/projects/{pid}/chapters/2", json={"text": "1화 원고"}, headers=h)
    assert r.status_code == 200  # 재업로드는 거절하지 않는다
    d1 = (await client.get(f"/projects/{pid}/chapters/1", headers=h)).json()
    d2 = (await client.get(f"/projects/{pid}/chapters/2", headers=h)).json()
    assert d2["content_hash"] == d1["content_hash"]
