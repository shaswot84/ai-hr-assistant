from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import Request

from app.auth.provider import AuthProvider
from app.config.settings import get_settings
from app.contracts.auth import UserContext


class KeycloakProvider(AuthProvider):
    """OIDC/OAuth2 provider for Keycloak (dev mode) — one concrete provider.

    Validates an OIDC `access_token` passed as `Authorization: Bearer <token>`
    or a `X-Access-Token` header against the realm's JWKS, then builds a
    trusted UserContext from the token claims.
    """

    name = "keycloak"

    def __init__(self) -> None:
        """Load app settings and initialize an empty JWKS cache."""
        self._settings = get_settings()
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_cache_at = 0.0

    # -- helpers ------------------------------------------------------

    def _well_known(self) -> dict[str, Any]:
        """Fetch the realm's OIDC discovery document."""
        url = f"{self._settings.keycloak.issuer}/.well-known/openid-configuration"
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    def _jwks(self) -> dict[str, Any]:
        """Return the realm signing keys, refreshing the in-memory cache every 5 minutes."""
        # refresh cache every 5 minutes
        if self._jwks_cache and time.time() - self._jwks_cache_at < 300:
            return self._jwks_cache
        jwks_uri = self._well_known()["jwks_uri"]
        resp = httpx.get(jwks_uri, timeout=10.0)
        resp.raise_for_status()
        self._jwks_cache = resp.json()
        self._jwks_cache_at = time.time()
        return self._jwks_cache

    def _decode_token(self, token: str) -> dict[str, Any]:
        """Validate a JWT against the realm's JWKS and return its claims.

        Tries every key in the JWKS set; the token is only rejected when all
        keys fail validation.
        """
        jwks = self._jwks()
        for key in jwks.get("keys", []):
            alg = key.get("alg", "RS256")
            try:
                public = jwt.algorithms.get_default_algorithms()[alg].from_jwk(key)
                payload = jwt.decode(
                    token,
                    public,
                    algorithms=[alg],
                    audience=self._settings.keycloak.client_id,
                    issuer=self._settings.keycloak.issuer,
                    options={"verify_exp": True},
                )
                return payload  # type: ignore[no-any-return]
            except Exception:  # noqa: BLE001, S112 - try next key; token fails only if all keys fail
                continue
        raise ValueError("Unable to validate token against the realm JWKS.")

    # -- AuthProvider interface ---------------------------------------

    def authenticate(self, request: Any) -> UserContext | None:
        """Validate the Bearer/X-Access-Token header and build a trusted UserContext.

        Returns None (unauthenticated) if no token is present or validation fails.
        """
        req: Request = request
        auth = req.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        if not token:
            token = req.headers.get("x-access-token")
        if not token:
            return None
        try:
            payload = self._decode_token(token)
        except Exception:  # noqa: BLE001 - any validation failure means unauthenticated
            return None

        realm_access = payload.get("realm_access") or {}
        roles = set(realm_access.get("roles", []) or [])
        # coarse role priority: HR_ADMIN > EMPLOYEE > CANDIDATE
        role = "EMPLOYEE"
        for candidate in ("HR_ADMIN", "EMPLOYEE", "CANDIDATE"):
            if candidate in roles:
                role = candidate
                break
        email = payload.get("email") or payload.get("preferred_username") or payload.get("sub")
        name = payload.get("name") or payload.get("preferred_username") or payload["sub"]
        return UserContext(
            subject=payload["sub"],
            email=email,
            display_name=name,
            coarse_role=role,
        )

    def build_login_url(self, redirect_uri: str) -> str | None:
        """Return the Keycloak authorization-code login URL for the given redirect URI."""
        return (
            f"{self._settings.keycloak.issuer}/protocol/openid-connect/auth"
            f"?response_type=code&client_id={self._settings.keycloak.client_id}"
            f"&redirect_uri={redirect_uri}&scope=openid"
        )

    def exchange_code(self, code: str, redirect_uri: str) -> UserContext:
        """Exchange an authorization code for tokens, then build a UserContext from the access token."""
        resp = httpx.post(
            f"{self._settings.keycloak.issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._settings.keycloak.client_id,
                "client_secret": self._settings.keycloak.client_secret,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = self._decode_token(resp.json()["access_token"])
        email = payload.get("email") or payload.get("preferred_username") or payload["sub"]
        realm_access = payload.get("realm_access") or {}
        roles = set(realm_access.get("roles", []) or [])
        role = "EMPLOYEE"
        for candidate in ("HR_ADMIN", "EMPLOYEE", "CANDIDATE"):
            if candidate in roles:
                role = candidate
                break
        return UserContext(
            subject=payload["sub"],
            email=email,
            display_name=payload.get("preferred_username", payload["sub"]),
            coarse_role=role,
        )

    def build_logout_url(self, redirect_uri: str) -> str | None:
        """Return the Keycloak logout URL that redirects back to the given URI."""
        return (
            f"{self._settings.keycloak.issuer}/protocol/openid-connect/logout"
            f"?client_id={self._settings.keycloak.client_id}&redirect_uri={redirect_uri}"
        )