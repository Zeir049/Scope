"""테스트 공용 헬퍼."""
from __future__ import annotations

import asyncio

from httpx import AsyncClient


async def poll_result(
    client: AsyncClient,
    project_id: str,
    chapter_no: int,
    headers: dict[str, str],
    tries: int = 30,
    stop: tuple[str, ...] = ("reviewed", "saved", "failed"),
) -> dict:
    """결과가 지정한 상태(stop) 중 하나가 될 때까지 폴링.

    기본은 검수 완료/저장/실패까지 기다린다(편의 analyze·검수 흐름).
    1차 추출만 기다리려면 stop=("extracted", "failed") 처럼 넘긴다.
    """
    for _ in range(tries):
        r = await client.get(
            f"/projects/{project_id}/chapters/{chapter_no}/result", headers=headers
        )
        body = r.json()
        if body.get("status") in stop:
            return body
        await asyncio.sleep(0.3)
    return {"status": "timeout"}


# 수동 저장 흐름(review → reviewed → POST /save)을 검증하는 테스트용 review 바디.
# 기본(auto_save=true)이면 서버가 reviewed 다음 saved 까지 진행한다(D4).
MANUAL_SAVE = {"auto_save": False}
