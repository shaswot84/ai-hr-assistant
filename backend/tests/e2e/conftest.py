"""E2E test fixtures — reuse the unit suite's DB + identity fixtures.

The e2e tree drives the REAL supervisor graph (the same wiring the chat
layer uses: build_supervisor_graph with a wired leave node) over the same
SQLite schema and seeded identities the unit suite uses. The fixtures are
re-exported from tests.unit.conftest rather than duplicated, so the e2e
tests exercise exactly the same DB setup as every other suite.
"""

from __future__ import annotations

from tests.unit.conftest import (  # noqa: F401
    _clean_tables,
    _schema,
    candidate_context,
    candidate_password,
    db,
    employee_context,
    employee_password,
    manager_context,
    manager_password,
)
