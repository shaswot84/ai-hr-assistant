from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_provider, get_current_user
from app.auth.jwt import JwtAuthProvider
from app.auth.provider import AuthProvider
from app.contracts.auth import UserContext
from app.db.session import get_db
from app.repositories.audit import AuditRepo

router = APIRouter(prefix="/api/auth", tags=["auth"])



class MeResponse(BaseModel):
    """Response body describing the authenticated user."""

    user: UserContext


class LoginRequest(BaseModel):
    """Credentials supplied at login (email + password)."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """JWT access token plus the resolved user context."""

    access_token: str
    token_type: str = "bearer"
    user: UserContext


@router.get("/me", response_model=MeResponse)
async def me(user: UserContext = Depends(get_current_user)) -> MeResponse:
    """Return the identity of the currently authenticated user."""
    return MeResponse(user=user)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    provider: AuthProvider = Depends(get_auth_provider),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Exchange email + password for a signed JWT access token."""
    if not isinstance(provider, JwtAuthProvider):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT authentication is not enabled.",
        )
    result = await provider.login(body.email, body.password)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    access_token, context, app_user = result
    await AuditRepo(db).record(
        actor_user_id=app_user.user_id,
        action="LOGIN",
        target_type="application_user",
        target_id=app_user.user_id,
        new_state={"email": context.email, "coarse_role": context.coarse_role},
    )
    await db.commit()
    return LoginResponse(access_token=access_token, user=context)

