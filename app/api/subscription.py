"""구독 라우터. (ENABLE_SUBSCRIPTION)"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.schemas.subscription import PlanUpdate, SubscriptionOut
from app.service.subscription_service import SubscriptionService

router = APIRouter(tags=["subscription"])


@router.get("/me/subscription", response_model=SubscriptionOut)
async def get_subscription(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    return await SubscriptionService(session).get(user)


@router.put("/me/subscription", response_model=SubscriptionOut)
async def update_subscription(
    body: PlanUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    return await SubscriptionService(session).set_plan(user, body.plan)
