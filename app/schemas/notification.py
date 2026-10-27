"""알림 스키마. (ENABLE_NOTIFICATIONS)"""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    message: str
    is_read: bool
    created_at: dt.datetime
