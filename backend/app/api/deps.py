from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.container import Container
from app.errors import ForbiddenError
from app.security import Actor, Permission, Role, has_permission


class UnauthenticatedError(ForbiddenError):
    status_code = 401
    code = "unauthenticated"


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_session(container: Container = Depends(get_container)) -> Iterator[Session]:
    """Endpoints commit explicitly; anything not committed is rolled back."""
    session = container.sessionmaker()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_actor(
    x_demo_user: str | None = Header(default=None),
    x_demo_role: str | None = Header(default=None),
) -> Actor:
    # POC ONLY. Replace with SSO/OIDC token validation in production.
    if not x_demo_user or not x_demo_role:
        raise UnauthenticatedError("Sign in required (X-Demo-User and X-Demo-Role headers)")
    try:
        role = Role(x_demo_role)
    except ValueError as exc:
        raise UnauthenticatedError(f"Unknown role '{x_demo_role}'") from exc
    if role == Role.SYSTEM:
        raise UnauthenticatedError("The system role cannot be used by a person")
    return Actor(username=x_demo_user.strip()[:120], role=role)


def require(permission: Permission):
    def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if not has_permission(actor, permission):
            raise ForbiddenError(f"Your role ({actor.role.value}) is not allowed to do this ({permission.value})")
        return actor

    return dependency
