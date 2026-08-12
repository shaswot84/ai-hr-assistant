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

# EnvFileSettingRepo (app_settings) reads/writes a real file on disk — point
# it at a throwaway temp file so tests never touch the project's real .env
# (which holds live secrets), matching the DB temp-file pattern above.
_settings_env_file = tempfile.NamedTemporaryFile(suffix=".env", delete=False)  # noqa: SIM115
os.environ["SETTINGS_ENV_FILE_PATH"] = _settings_env_file.name


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_database_file():
    """Remove the throwaway SQLite file and settings-env file once the test session is done."""
    yield
    for path in (_db_file.name, _settings_env_file.name):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
