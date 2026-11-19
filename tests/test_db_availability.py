import os

import psycopg2
import pytest
from dotenv import load_dotenv

from capmkt_data_platform.db import connect
from capmkt_data_platform.settings import Settings, get_settings

load_dotenv()


@pytest.mark.integration
def test_db_availability():
    c = psycopg2.connect(
        host=os.getenv("PGHOST"),
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
    )
    assert c.get_dsn_parameters()["dbname"] == os.getenv("PGDATABASE")
    c.close()


@pytest.mark.integration
def test_database_is_reachable():
    s = get_settings()
    with connect(s) as conn:
        assert conn.execute("select current_database()").fetchone()[0] == s.pgdatabase
        schemas = conn.execute(
            "select schema_name from information_schema.schemata"
        ).fetchall()
        print(schemas)
        for schem in [
            ("public",),
            ("information_schema",),
            ("pg_catalog",),
            ("dq",),
            ("snapshots",),
            ("monitoring",),
            ("recon",),
            ("core",),
            ("int",),
            ("stg",),
            ("ref",),
            ("audit",),
            ("raw",),
        ]:
            assert schem in schemas


def test_postgres_settings_come_from_env(monkeypatch):
    monkeypatch.setenv("PGDATABASE", "capmkt_test")
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("PGPASSWORD", "s3cret")
    s = Settings(_env_file=None)
    assert (s.pgdatabase, s.pgport) == ("capmkt_test", 5433)
    assert s.pgpassword.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(s)  # the secret never appears in logs


def test_connect_without_password_raises_clear_error(monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="PGPASSWORD"):
        connect(Settings(_env_file=None))
