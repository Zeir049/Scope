"""구독(요금제) 스키마. (ENABLE_SUBSCRIPTION)"""
from __future__ import annotations

from pydantic import BaseModel


class SubscriptionOut(BaseModel):
    plan: str
    features: list[str]


class PlanUpdate(BaseModel):
    plan: str  # free | pro
