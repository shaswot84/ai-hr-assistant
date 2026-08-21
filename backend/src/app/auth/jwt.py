from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.passwords import verify_password
from app.auth.provider import AuthProvider
from app.config.settings import get_settings
from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Person


class JwtAuthProvider(AuthProvider):
    """Self-issued JWT authentication — the single runtime identity source."""

    name = "jwt"

    def __init__(self, db: AsyncSession | None = None) -> None:
        """Load settings and optionally bind an async DB session."""
        self._settings = get_settings()
        self._db = db
        if not self._settings.jwt.secret_key:
            raise RuntimeError("JWT_SECRET_KEY is not configured.")

    # -- helpers ------------------------------------------------------

    def _encode(self, subject: str) -> str:
        """Sign a short-lived access token for the given auth subject."""
        now = datetime.now(UTC)
        payload = {
            "sub": subject,
            "iss": self._settings.jwt.issuer,
            "iat": now,
            "exp": now + timedelta(minutes=self._settings.jwt.access_token_expire_minutes),
        }
        return jwt.encode(payload, self._settings.jwt.secret_key, algorithm=self._settings.jwt.algorithm)

    def _decode(self, token: str) -> dict[str, Any]:
        """Validate and decode a token; raises jwt.PyJWTError when invalid or expired."""
        return jwt.decode(
            token,
            self._settings.jwt.secret_key,
            algorithms=[self._settings.jwt.algorithm],
            issuer=self._settings.jwt.issuer,
            options={"require": ["sub", "exp"]},
        )

    def _to_context(self, app_user: ApplicationUser) -> UserContext:
        """Build a trusted UserContext from the authoritative `application_user` row."""
        person: Person = app_user.person
        name = f"{person.first_name} {person.last_name}".strip()
        return UserContext(
            subject=app_user.external_subject,
            email=person.email,
            display_name=name or person.email,
            coarse_role=app_user.coarse_role,
        )

    async def _find_by_subject(self, subject: str) -> ApplicationUser | None:
        """Look up an ApplicationUser by (identity_provider="local", external_subject)."""
        if self._db is None:
            return None
        stmt = (
            select(ApplicationUser)
            .options(selectinload(ApplicationUser.person))
            .where(
                ApplicationUser.identity_provider == "local",
                ApplicationUser.external_subject == subject,
            )
        )
        return await self._db.scalar(stmt)

    def create_access_token(self, subject: str) -> str:
        """Issue a signed access token for a subject (used by the login route)."""
        return self._encode(subject)

    async def login(self, email: str, password: str) -> tuple[str, UserContext, ApplicationUser] | None:
        """Verify credentials and return (access_token, UserContext, ApplicationUser), or None."""
        app_user = await self.verify_credentials(email, password)
        if app_user is None:
            return None
        return self.create_access_token(app_user.external_subject), self._to_context(app_user), app_user

    async def verify_credentials(self, email: str, password: str) -> ApplicationUser | None:
        """Return the ApplicationUser whose email+password match, else None."""
        if self._db is None:
            return None
        normalized = email.strip().lower()
        person = await self._db.scalar(select(Person).where(Person.email == normalized))
        if person is None:
            return None
        stmt = (
            select(ApplicationUser)
            .options(selectinload(ApplicationUser.person))
            .where(
                ApplicationUser.identity_provider == "local",
                ApplicationUser.person_id == person.person_id,
            )
        )
        app_user = await self._db.scalar(stmt)
        if app_user is None or not app_user.password_hash or app_user.status != "ACTIVE":
            return None
        if not verify_password(password, app_user.password_hash):
            return None
        return app_user

    # -- AuthProvider interface ---------------------------------------

    async def authenticate(self, request: Any) -> UserContext | None:
        """Validate the Bearer token and build a trusted UserContext from the DB row."""
        req: Request = request
        auth = req.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        if not token:
            return None
        try:
            payload = self._decode(token)
        except Exception:  # noqa: BLE001
            return None
        subject = payload.get("sub")
        if not subject:
            return None
        app_user = await self._find_by_subject(subject)
        if app_user is None or app_user.status != "ACTIVE":
            return None
        return self._to_context(app_user)

    def build_login_url(self, redirect_uri: str) -> str | None:
        """Login is a JSON endpoint, not an IdP redirect."""
        return None

    def exchange_code(self, code: str, redirect_uri: str) -> UserContext:
        """Not supported — JWT auth has no authorization-code flow."""
        raise NotImplementedError("JWT auth uses a direct login endpoint, not an authorization code flow.")

    def build_logout_url(self, redirect_uri: str) -> str | None:
        """JWT is stateless; the client drops the token (no IdP logout)."""
        return None

