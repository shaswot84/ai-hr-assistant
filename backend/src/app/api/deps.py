from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.dev_stub import DevStubProvider
from app.auth.keycloak import KeycloakProvider
from app.auth.provider import AuthProvider
from app.config.settings import get_settings
from app.contracts.auth import UserContext

_bearer = HTTPBearer(auto_error=False)


def get_auth_provider() -> AuthProvider:
    """Instantiate the active AuthProvider based on app settings (keycloak or dev stub)."""
    settings = get_settings()
    if settings.auth.provider == "keycloak":
        return KeycloakProvider()
    return DevStubProvider()


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UserContext:
    """Resolve the authenticated user from the active AuthProvider.

    The dev stub reads X-Dev-* headers / session cookie; Keycloak reads the
    Bearer token. Authorization (role checks) happens in the capability layer.
    """
    provider = get_auth_provider()
    user = provider.authenticate(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_role(*roles: str):
    """Return a FastAPI dependency that enforces that the user's coarse role is in `roles`."""

    def checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        """Ensure the current user holds one of the required roles, else raise 403."""
        if user.coarse_role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker
