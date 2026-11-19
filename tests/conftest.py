"""Shared pytest fixtures.

Integration tests write to PostgreSQL, so they are locked to the database named
capmkt_test. The fixtures force that database name AND re-check it with
SELECT current_database() before any row is touched.
"""

from __future__ import annotations

import psycopg
import pytest

from capmkt_data_platform.db import connect
from capmkt_data_platform.settings import Settings, get_settings

TEST_DB = "capmkt_test"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return get_settings().model_copy(update={"pgdatabase": TEST_DB})


def _assert_test_database(conn) -> None:
    name = conn.execute("SELECT current_database()").fetchone()[0]
    assert name == TEST_DB, f"refusing to run: connected to '{name}', not '{TEST_DB}'"


@pytest.fixture
def audit_conn(test_settings):
    """Autocommit connection. Starts every test with empty raw and audit tables."""
    try:
        conn = connect(test_settings, autocommit=True)
    except (
        psycopg.Error,
        RuntimeError,
    ) as exc:  # db down, wrong password, no capmkt_test, no PGPASSWORD
        pytest.skip(f"test database '{TEST_DB}' unavailable: {exc}")
    try:
        _assert_test_database(conn)
        conn.execute("TRUNCATE raw.bhavcopy_cm, raw.sim_trades")
        conn.execute("DELETE FROM audit.ingestion_log")
        yield conn
    finally:
        conn.close()


@pytest.fixture
def data_conn(test_settings, audit_conn):
    """Normal (transactional) connection for loads. Depends on audit_conn for the clean start."""
    conn = connect(test_settings)
    try:
        _assert_test_database(conn)
        conn.rollback()  # the check above opened a transaction; leave the connection idle
        yield conn
    finally:
        conn.rollback()
        conn.close()
