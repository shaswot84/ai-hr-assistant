from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.contracts.auth import UserContext


class AuthProvider(ABC):
    """Swappable identity/authentication seam.

    Implementations: DevStubProvider (local dev/CI, no infra) and
    KeycloakProvider (OIDC). FastAPI depends only on this interface +
    UserContext. Swapping providers must never require changes in
    recruitment code.
    """

    @abstractmethod
    def authenticate(self, request: Any) -> UserContext | None:
        """Resolve the current request to a UserContext, or None if unauthenticated."""

    @abstractmethod
    def build_login_url(self, redirect_uri: str) -> str | None:
        """Return an IdP login URL, or None for providers without a redirect flow."""

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> UserContext:
        """Exchange an authorization code for a UserContext (OIDC providers)."""

    @abstractmethod
    def build_logout_url(self, redirect_uri: str) -> str | None:
        """Return an IdP logout URL, or None for providers without one."""
