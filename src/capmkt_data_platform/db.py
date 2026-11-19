# Database connection helper utilities for the capmkt_data_platform package.

from __future__ import annotations

import psycopg

from capmkt_data_platform.settings import Settings


def connect(settings: Settings, *, autocommit: bool = False) -> psycopg.Connection:
    if settings.pgpassword is None:
        raise RuntimeError("PGPASSWORD is not set. Add it to .env or the environment.")
    return psycopg.connect(
        host=settings.pghost,
        port=settings.pgport,
        dbname=settings.pgdatabase,
        user=settings.pguser,
        password=settings.pgpassword.get_secret_value(),
        autocommit=autocommit,
        connect_timeout=5,
    )
