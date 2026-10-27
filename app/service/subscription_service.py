"""구독 비즈니스 로직. (ENABLE_SUBSCRIPTION)

결제 연동은 범위 밖 — plan 상태(free/pro)만 관리한다.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.models import User
from app.schemas.subscription import SubscriptionOut

logger = logging.getLogger(__name__)

PLAN_FEATURES: dict[str, list[str]] = {
    "free": ["프로젝트 3개", "회차 분석"],
    "pro": ["프로젝트 무제한", "회차 분석", "공유 링크", "우선 지원"],
}


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, user: User) -> SubscriptionOut:
        return SubscriptionOut(
            plan=user.plan, features=PLAN_FEATURES.get(user.plan, [])
        )

    async def set_plan(self, user: User, plan: str) -> SubscriptionOut:
        if plan not in PLAN_FEATURES:
            raise DomainError(
                f"알 수 없는 plan: {plan}. 가능: {', '.join(PLAN_FEATURES)}"
            )
        user.plan = plan
        await self.s.commit()
        logger.info("plan changed: user=%s -> %s", user.id, plan)
        return SubscriptionOut(plan=plan, features=PLAN_FEATURES[plan])
