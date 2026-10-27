"""회차 재업로드(PUT) + 파일 업로드(multipart, 서버 파싱) 테스트.

- 저장(saved)된 회차도 PUT으로 원고 교체 → uploaded 회귀 → 재분석·재저장
- PUT 오류 케이스 (본문 없음 400, 미존재 404)
- docx multipart 업로드 → 서버 파서가 텍스트 추출
- PUT multipart 교체
"""
from __future__ import annotations

import io

from httpx import AsyncClient

from tests.util import poll_result


async def _upload(client: AsyncClient, pid: str, h: dict, no: int = 1, text: str = "원본 원고입니다."):
    r = await client.post(
        f"/projects/{pid}/chapters", json={"chapter_no": no, "text": text}, headers=h
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _analyze_to_saved(client: AsyncClient, pid: str, h: dict, no: int = 1):
    assert (await client.post(f"/projects/{pid}/chapters/{no}/analyze", headers=h)).status_code == 202
    assert (await poll_result(client, pid, no, h))["status"] == "reviewed"
    assert (await client.post(f"/projects/{pid}/chapters/{no}/save", headers=h)).status_code == 200


async def test_reupload_after_saved_allows_reanalysis(client: AsyncClient, auth_headers: dict, project_id: str):
    """저장된 회차도 PUT으로 원고 교체하면 다시 분석·저장할 수 있다 (수정 원고 흐름)."""
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1)
    await _analyze_to_saved(client, pid, h, 1)

    # 저장된 상태에선 재분석 불가(기존 규칙 유지 확인)
    assert (await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)).status_code == 409

    # 재업로드 → 상태 uploaded 회귀 + 제목 갱신
    r = await client.put(
        f"/projects/{pid}/chapters/1",
        json={"title": "수정본", "text": "수정된 원고"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "uploaded" and body["title"] == "수정본"

    # 재분석 → 재저장까지 정상 (캐논은 append-only 버전업)
    await _analyze_to_saved(client, pid, h, 1)


async def test_reupload_errors(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1)
    # 본문 없음 → 400
    assert (await client.put(f"/projects/{pid}/chapters/1", json={"title": "x"}, headers=h)).status_code == 400
    # 미존재 회차 → 404
    assert (await client.put(f"/projects/{pid}/chapters/99", json={"text": "y"}, headers=h)).status_code == 404


async def test_multipart_docx_upload_parses_on_server(client: AsyncClient, auth_headers: dict, project_id: str):
    """docx 파일을 multipart로 올리면 서버 파서가 텍스트를 추출한다."""
    import docx

    h, pid = auth_headers, project_id
    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph("도시의 마법은 달빛 아래에서만 흐른다.")
    d.save(buf)

    r = await client.post(
        f"/projects/{pid}/chapters",
        data={"chapter_no": "1", "title": "1화.docx"},
        files={
            "file": (
                "1화.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=h,
    )
    assert r.status_code == 201, r.text

    # 분석까지 돌려 원문이 실제 텍스트로 추출·저장됐는지 확인
    assert (await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)).status_code == 202
    res = await poll_result(client, pid, 1, h)
    assert res["status"] == "reviewed"
    assert "달빛" in res.get("highlighted_text", "")


async def test_multipart_put_reupload(client: AsyncClient, auth_headers: dict, project_id: str):
    """PUT도 multipart(file)로 원고를 교체할 수 있다."""
    h, pid = auth_headers, project_id
    await _upload(client, pid, h, 1)
    r = await client.put(
        f"/projects/{pid}/chapters/1",
        files={"file": ("수정.txt", "교체된 본문".encode("utf-8"), "text/plain")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "uploaded"
