"""Unit tests for knowledge role-access helpers."""

import pytest

from app.contracts.auth import UserContext
from app.knowledge.access import (
    ALL_ACCESS_ROLES,
    SELECTABLE_ACCESS_ROLES,
    access_roles_for,
    validate_access_roles,
)


def _user(role: str) -> UserContext:
    return UserContext(subject="s-1", email="a@x.com", display_name="A", coarse_role=role)


def test_access_roles_for_anonymous_visitor():
    assert access_roles_for(None) == ["VISITOR"]


def test_access_roles_for_authenticated_roles():
    assert access_roles_for(_user("CANDIDATE")) == ["CANDIDATE"]
    assert access_roles_for(_user("EMPLOYEE")) == ["EMPLOYEE"]


def test_access_roles_for_hr_admin_is_unrestricted():
    assert access_roles_for(_user("HR_ADMIN")) is None


def test_validate_access_roles_merges_hr_admin():
    assert validate_access_roles(["VISITOR", "CANDIDATE"]) == [
        "VISITOR",
        "CANDIDATE",
        "HR_ADMIN",
    ]


def test_validate_access_roles_deduplicates_and_preserves_hr():
    assert validate_access_roles(["HR_ADMIN", "EMPLOYEE", "HR_ADMIN"]) == [
        "HR_ADMIN",
        "EMPLOYEE",
    ]


def test_validate_access_roles_rejects_empty():
    with pytest.raises(ValueError):
        validate_access_roles([])


def test_validate_access_roles_rejects_unknown():
    with pytest.raises(ValueError):
        validate_access_roles(["SUPER_ADMIN"])


def test_constants_cover_the_roles():
    assert set(ALL_ACCESS_ROLES) == {"HR_ADMIN", "EMPLOYEE", "CANDIDATE", "VISITOR"}
    assert set(SELECTABLE_ACCESS_ROLES) == {"EMPLOYEE", "CANDIDATE", "VISITOR"}
