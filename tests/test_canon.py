"""캐논 테스트: append-only 버전관리(필수) + 6탭 조회 형태."""
from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import CanonWorldview, Project
from app.repository.user_repo import UserRepository
from app.service.canon_service import CanonService
from tests.util import poll_result


async def test_append_only_versioning():
    """같은 entity_key를 변경하면: 옛 버전 보존 + is_current 1개 + version 증가."""
    async with SessionLocal() as s:
        user = await UserRepository(s).create(
            f"cv_{uuid.uuid4().hex[:8]}@x.com", hash_password("x"), "t"
        )
        project = Project(owner_id=user.id, name="canon-test")
        s.add(project)
        await s.flush()
        pid = project.id

        cs = CanonService(s)
        # v1 삽입
        await cs.merge_delta(pid, {"worldview": [{"entity_key": "k", "item": "v1"}]}, 1)
        # 동일 내용 → 멱등(버전 안 늘어남)
        await cs.merge_delta(pid, {"worldview": [{"entity_key": "k", "item": "v1"}]}, 2)
        # 내용 변경 → supersede + v2
        await cs.merge_delta(pid, {"worldview": [{"entity_key": "k", "item": "v2"}]}, 3)
        await s.commit()

        total = await s.scalar(
            select(func.count()).select_from(CanonWorldview).where(
                CanonWorldview.project_id == pid, CanonWorldview.entity_key == "k"
            )
        )
        current = (
            await s.execute(
                select(CanonWorldview).where(
                    CanonWorldview.project_id == pid,
                    CanonWorldview.entity_key == "k",
                    CanonWorldview.is_current.is_(True),
                )
            )
        ).scalars().all()

    assert total == 2  # v1(보존) + v2 — 멱등 호출은 행을 안 만듦
    assert len(current) == 1
    assert current[0].version == 2 and current[0].item == "v2"


async def _build_canon(client: AsyncClient, pid: str, h: dict):
    await client.post(f"/projects/{pid}/chapters", json={"chapter_no": 1, "text": "본문"}, headers=h)
    await client.post(f"/projects/{pid}/chapters/1/analyze", headers=h)
    await poll_result(client, pid, 1, h)
    await client.post(f"/projects/{pid}/chapters/1/save", headers=h)


async def test_canon_views(client: AsyncClient, auth_headers: dict, project_id: str):
    h, pid = auth_headers, project_id
    await _build_canon(client, pid, h)

    # 평면 리스트 탭
    r = await client.get(f"/projects/{pid}/canon?view=worldview", headers=h)
    b = r.json()
    assert b["view"] == "worldview" and isinstance(b["items"], list) and b["items"]

    # 인물 탭 = 그래프
    r = await client.get(f"/projects/{pid}/canon?view=characters", headers=h)
    b = r.json()
    assert "nodes" in b and "edges" in b and b["nodes"]

    # 복선 탭 = 트리(parent_id 필드)
    r = await client.get(f"/projects/{pid}/canon?view=foreshadowing", headers=h)
    assert all("parent_id" in it for it in r.json()["items"])

    # 잘못된 view → 400
    assert (await client.get(f"/projects/{pid}/canon?view=bogus", headers=h)).status_code == 400


async def test_canon_requires_ownership(client: AsyncClient, auth_headers: dict, project_id: str):
    r2 = await client.post(
        "/auth/register",
        json={"email": f"o_{uuid.uuid4().hex[:8]}@x.com", "password": "secret123"},
    )
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = await client.get(f"/projects/{project_id}/canon?view=worldview", headers=h2)
    assert r.status_code == 403
