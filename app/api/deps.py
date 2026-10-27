"""라우터 공통 의존성: 현재 사용자 인증."""
from __future__ import annotations

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import AuthError
from app.core.security import decode_access_token
from app.models import User
from app.repository.user_repo import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Authorization: Bearer <token> 검증 → User. 실패 시 401."""
    if cred is None:
        raise AuthError("인증이 필요합니다.")
    user_id_str = decode_access_token(cred.credentials)
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as e:
        raise AuthError("유효하지 않은 토큰입니다.") from e
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise AuthError("유효하지 않은 토큰입니다.")
    return user
