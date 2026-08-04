from __future__ import annotations

from typing import Any

from fastapi import Response
from starlette.datastructures import Headers

from app.auth.provider import AuthProvider
from app.config.settings import get_settings
from app.contracts.auth import UserContext

# cookie name for the dev session
DEV_SESSION_COOKIE = "hr_dev_session"
DEV_SESSION_MAX_AGE = 60 * 60 * 12  # 12h


class DevStubProvider(AuthProvider):
    """Development-only auth provider — no external identity service.

    A DevLoginResponse / header (`X-Dev-Subject`, `X-Dev-Role`) or the
    `hr_dev_session` cookie identifies the caller. Never used in production;
    it exists so the recruitment module can be built, demoed and tested
    without a Keycloak container.
    """

    name = "dev_stub"

    def __init__(self) -> None:
        self._settings = get_settings()

    def _subject_to_email(self, subject: str) -> str:
        return f"{subject}@example.com"

    def authenticate(self, request: Any) -> UserContext | None:
        headers: Headers = getattr(request, "headers", Headers())
        cookie = getattr(request, "cookies", {})
        subject = headers.get("x-dev-subject")
        role = headers.get("x-dev-role")
        email = headers.get("x-dev-email")
        name = headers.get("x-dev-name")
        if not subject or not role:
            raw = cookie.get(DEV_SESSION_COOKIE)
            if raw:
                parts = raw.split("|")
                subject = parts[0]
                role = parts[1]
                email = parts[2] if len(parts) > 2 else None
                name = parts[3] if len(parts) > 3 else None
        if not subject or not role:
            return None
        if role not in {"HR_ADMIN", "EMPLOYEE", "CANDIDATE"}:
            return None
        email = email or self._subject_to_email(subject)
        name = name or subject
        return UserContext(subject=subject, email=email, display_name=name, coarse_role=role)

    def set_session(self, response: Response, user: UserContext) -> None:
        """Persist the stub identity into an httpOnly cookie (dev login)."""
        response.set_cookie(
            DEV_SESSION_COOKIE,
            value=f"{user.subject}|{user.coarse_role}|{user.email}|{user.display_name}",
            max_age=DEV_SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )

    def clear_session(self, response: Response) -> None:
        response.delete_cookie(DEV_SESSION_COOKIE, path="/")

    def build_login_url(self, redirect_uri: str) -> str | None:
        return None

    def exchange_code(self, code: str, redirect_uri: str) -> UserContext:
        raise NotImplementedError("Dev stub has no authorization code flow.")

    def build_logout_url(self, redirect_uri: str) -> str | None:
        return None
