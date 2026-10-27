"""소유권 검사. 모든 project/chapter 접근은 이걸 먼저 통과해야 한다 (CLAUDE.md 규칙 5)."""
from __future__ import annotations

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Project, User


def assert_owned(project: Project | None, user: User) -> Project:
    """프로젝트가 존재하고 현재 사용자 소유인지 검증. 통과 시 project 반환."""
    if project is None:
        raise NotFoundError("프로젝트를 찾을 수 없습니다.")
    if project.owner_id != user.id:
        raise PermissionDeniedError("접근 권한이 없습니다.")
    return project
