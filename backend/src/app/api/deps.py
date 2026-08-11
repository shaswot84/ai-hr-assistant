from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.jwt import JwtAuthProvider
from app.auth.provider import AuthProvider
from app.config.settings import get_settings
from app.contracts.auth import UserContext
from app.db.sync_session import get_db

_bearer = HTTPBearer(auto_error=False)


def get_auth_provider(db: Session = Depends(get_db)) -> AuthProvider:
    """Instantiate the active AuthProvider (self-issued JWT is the only provider)."""
    settings = get_settings()
    if settings.auth.provider != "jwt":
        raise RuntimeError(f"Unsupported auth provider configured: {settings.auth.provider!r}")
    return JwtAuthProvider(db=db)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    provider: AuthProvider = Depends(get_auth_provider),
) -> UserContext:
    """Resolve the authenticated user from the signed JWT.

    The short-lived HS256 JWT is verified against the local secret; the coarse
    role is re-read from the DB on every request (authoritative). Authorization
    (role checks) happens in the capability layer, not here.
    """
    user = provider.authenticate(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_optional_user(
    request: Request,
    provider: AuthProvider = Depends(get_auth_provider),
) -> UserContext | None:
    """Resolve the authenticated user, or None for public (anonymous) routes.

    Used by endpoints anyone may call (e.g. browsing open vacancies): a valid
    token still resolves to a user so the route can tailor the response, but
    no token / an invalid token is treated as an anonymous visitor rather than
    a 401.
    """
    return provider.authenticate(request)


def require_role(*roles: str):
    """Return a FastAPI dependency that enforces that the user's coarse role is in `roles`."""

    def checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        """Ensure the current user holds one of the required roles, else raise 403."""
        if user.coarse_role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker
