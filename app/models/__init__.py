"""모든 ORM 모델을 여기서 import → Base.metadata 에 등록(Alembic autogenerate용)."""
from app.models.analysis import AnalysisResult, Contradiction, ContradictionStatus
from app.models.auth_reset import PasswordResetToken
from app.models.base import Base
from app.models.canon import (
    CanonCharacter,
    CanonEvent,
    CanonForeshadowing,
    CanonRelation,
    CanonSpace,
    CanonTimeline,
    CanonWorldview,
)
from app.models.chapter import Chapter, ChapterKind, ChapterStatus
from app.models.chat import ChatMessage, ChatSession
from app.models.notification import Notification
from app.models.project import Project
from app.models.share import ShareLink
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Project",
    "Chapter",
    "ChapterStatus",
    "ChapterKind",
    "AnalysisResult",
    "Contradiction",
    "ContradictionStatus",
    "CanonWorldview",
    "CanonCharacter",
    "CanonRelation",
    "CanonTimeline",
    "CanonSpace",
    "CanonEvent",
    "CanonForeshadowing",
    # 확장 기능(비밀번호 재설정 · 공유 · 채팅 · 알림)
    "PasswordResetToken",
    "ShareLink",
    "ChatSession",
    "ChatMessage",
    "Notification",
]
