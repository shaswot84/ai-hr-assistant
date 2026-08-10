from __future__ import annotations

from pydantic import BaseModel


class UserContext(BaseModel):
    """Trusted identity + coarse role built by an AuthProvider.

    Auth answers WHO you are and your coarse role. Resolving employee_id /
    candidate_id / manager relationships is the identity layer's job
    (`services.identity.IdentityService`), not auth.
    """

    subject: str
    email: str
    display_name: str
    coarse_role: str  # HR_ADMIN | EMPLOYEE | CANDIDATE
