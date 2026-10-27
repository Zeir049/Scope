"""구글 로그인(Firebase) 토큰 교환 라우터. ENABLE_FIREBASE_AUTH일 때만 등록.

프론트(최종 UI)는 Firebase 팝업으로 구글 로그인한 뒤, 받은 ID 토큰을
여기로 보내 자체 JWT로 교환한다. 이후 요청은 기존 Bearer 인증과 동일.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.auth import FirebaseLoginRequest, TokenResponse
from app.service.auth_service import AuthService

router = APIRouter(tags=["auth"])


@router.post("/auth/firebase", response_model=TokenResponse)
async def firebase_login(
    body: FirebaseLoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    return await AuthService(session).login_with_firebase(body.id_token)
