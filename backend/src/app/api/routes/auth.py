from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr

from app.api.deps import get_auth_provider, get_current_user
from app.auth.dev_stub import DevStubProvider
from app.auth.provider import AuthProvider
from app.contracts.auth import UserContext

router = APIRouter(prefix="/api/auth", tags=["auth"])

VALID_ROLES = {"HR_ADMIN", "EMPLOYEE", "CANDIDATE"}


class DevLoginRequest(BaseModel):
    """Request body for the dev-only login endpoint."""

    role: str
    email: EmailStr | None = None
    name: str | None = None


class DevLoginResponse(BaseModel):
    """Response body describing the authenticated user."""

    user: UserContext


@router.get("/me", response_model=DevLoginResponse)
def me(user: UserContext = Depends(get_current_user)) -> DevLoginResponse:
    """Return the identity of the currently authenticated user."""
    return DevLoginResponse(user=user)


@router.post("/dev-login", response_model=DevLoginResponse)
def dev_login(
    body: DevLoginRequest,
    response: Response,
    provider: AuthProvider = Depends(get_auth_provider),
) -> DevLoginResponse:
    """Dev-only: switch identity/role via the stub provider (no Keycloak needed)."""
    if not isinstance(provider, DevStubProvider):
        raise HTTPException(status_code=404, detail="Dev login unavailable with this auth provider.")
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {sorted(VALID_ROLES)}")
    subject = f"{body.role.lower()}-{body.email or 'demo'}"
    user = UserContext(
        subject=subject,
        email=body.email or f"{subject}@example.com",
        display_name=body.name or body.role.replace("_", " ").title(),
        coarse_role=body.role,
    )
    provider.set_session(response, user)
    return DevLoginResponse(user=user)


@router.post("/logout")
def logout(
    response: Response,
    provider: AuthProvider = Depends(get_auth_provider),
) -> dict[str, bool]:
    """Clear the dev session cookie, if the active provider is the dev stub."""
    if isinstance(provider, DevStubProvider):
        provider.clear_session(response)
    return {"ok": True}
