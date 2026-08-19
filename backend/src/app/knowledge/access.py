"""Role-based access helpers for knowledge documents.

Every document carries a ``role_access`` allowlist (exact set of roles that
may retrieve it). The uploader picks the roles at submit time; ``HR_ADMIN``
is always present in the stored list (the upload form pins it), and at query
time an HR admin bypasses the filter entirely.
"""

from app.contracts.auth import UserContext

ALL_ACCESS_ROLES = ["HR_ADMIN", "EMPLOYEE", "CANDIDATE", "VISITOR"]

# Roles an uploader can actually choose (HR is pinned, not optional).
SELECTABLE_ACCESS_ROLES = ["EMPLOYEE", "CANDIDATE", "VISITOR"]


def access_roles_for(actor: UserContext | None) -> list[str] | None:
    """The requester's access tag for retrieval filtering.

    ``None`` means "no filter" — used for HR admins, who may always see
    every document. Anonymous visitors get ``["VISITOR"]``; authenticated
    users get their own coarse role.
    """
    if actor is None:
        return ["VISITOR"]
    if actor.coarse_role == "HR_ADMIN":
        return None
    return [actor.coarse_role]


def validate_access_roles(roles: list[str]) -> list[str]:
    """Validate and normalize an uploader-supplied access list.

    Raises ``ValueError`` on an empty list or an unknown role. ``HR_ADMIN``
    is always merged into the result so no stored tag can ever lack it.
    """
    if not roles:
        raise ValueError("role_access must contain at least one role")
    unknown = [role for role in roles if role not in ALL_ACCESS_ROLES]
    if unknown:
        raise ValueError(f"unknown role_access value(s): {', '.join(sorted(unknown))}")
    normalized = list(dict.fromkeys([*roles, "HR_ADMIN"]))
    return normalized
