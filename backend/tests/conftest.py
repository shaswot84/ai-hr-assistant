"""Environment bootstrap for the full test suite.

Pytest imports this before any test module. Integration tests import ``app.*``
at collection time, so if this only happened in ``tests/unit/conftest.py`` the
settings singleton would freeze the default Postgres URL before the unit suite
could switch to SQLite. Keeping the env setup here makes ``pytest tests`` run
hermetically without a live database.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_db_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)  # noqa: SIM115 - lives for the whole test session
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"
os.environ["AUTH_PROVIDER"] = "jwt"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-0123456789abcdef0123456789abcdef"
os.environ["MINIO_AUTO_INIT"] = "false"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_database_file():
    """Remove the throwaway SQLite file once the test session is done."""
    yield
    try:
        os.unlink(_db_file.name)
    except FileNotFoundError:
        pass
