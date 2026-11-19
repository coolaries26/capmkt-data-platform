"""Loader tests.

Unit tests need nothing. Integration tests need PostgreSQL with the project DDL applied
to the database 'capmkt_test' (see conftest.py); they are skipped if it is unreachable.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
from bhavcopy_fixtures import CFG, make_csv, make_zip, row
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from capmkt_data_platform.ingest.loader import (
    FAILED,
    SUCCESS,
    LoadResult,
    _table_identifier,
    load_day,
    record_download_failure,
    record_no_file,
)
from capmkt_data_platform.ingest.nse_client import DOWNLOADED, NO_FILE, DownloadResult

integration = pytest.mark.integration

D1 = date(
    2025, 3, 3
)  # fixed past dates: always before the database clock, inside a partition
D2 = date(2025, 3, 4)
DATASET = "bhavcopy_cm"


# --- helpers -------------------------------------------------------------------
def day_rows(day: date, n: int = 3, **overrides: str) -> list[dict[str, str]]:
    iso = day.isoformat()
    return [
        row(
            TradDt=iso,
            BizDt=iso,
            TckrSymb=f"SYM{i}",
            ISIN=f"INE00000{i:04d}",
            **overrides,
        )
        for i in range(n)
    ]


def landed(
    tmp_path, rows: list[dict[str, str]], day: date = D1, name: str | None = None
):
    """Write rows to a landed zip and return the DownloadResult the client would give."""
    content = make_zip(make_csv(rows))
    path = tmp_path / (name or f"BhavCopy_{day:%Y%m%d}.csv.zip")
    path.write_bytes(content)
    return DownloadResult(
        dataset=DATASET,
        trade_date=day,
        status=DOWNLOADED,
        url=f"https://example.test/{path.name}",
        path=path,
        http_status=200,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def fetch(conn, query: str, params=()) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def audit(conn) -> list[dict]:
    return fetch(conn, "SELECT * FROM audit.ingestion_log ORDER BY load_id")


def raw_count(conn, day: date | None = None) -> int:
    if day is None:
        return fetch(conn, "SELECT count(*) AS n FROM raw.bhavcopy_cm")[0]["n"]
    return fetch(
        conn, "SELECT count(*) AS n FROM raw.bhavcopy_cm WHERE trade_date = %s", (day,)
    )[0]["n"]


# --- unit tests (no database) ---------------------------------------------------
def test_table_identifier_accepts_schema_dot_table():
    assert _table_identifier("raw.bhavcopy_cm").as_string() == '"raw"."bhavcopy_cm"'


@pytest.mark.parametrize(
    "bad",
    [
        "bhavcopy_cm",
        "raw.bhavcopy_cm; DROP TABLE x",
        'raw."x"',
        "Raw.Table",
        "a.b.c",
        "",
    ],
)
def test_table_identifier_rejects_anything_but_schema_dot_table(bad):
    with pytest.raises(ValueError):
        _table_identifier(bad)


def test_load_result_to_dict_is_json_friendly():
    assert LoadResult(7, SUCCESS, rows_loaded=3).to_dict() == {
        "load_id": 7,
        "status": "SUCCESS",
        "rows_loaded": 3,
        "error": None,
    }


# --- integration: the happy path ------------------------------------------------
@integration
def test_load_day_inserts_rows_and_writes_a_complete_audit_row(
    tmp_path, audit_conn, data_conn
):
    dl = landed(tmp_path, day_rows(D1))
    result = load_day(audit_conn, data_conn, DATASET, CFG, dl)

    assert (result.status, result.rows_loaded, result.error) == (SUCCESS, 3, None)
    assert raw_count(audit_conn, D1) == 3

    (a,) = audit(audit_conn)
    assert a["load_id"] == result.load_id
    assert (a["dataset"], a["trade_date"], a["status"]) == (DATASET, D1, "SUCCESS")
    assert (a["rows_in_file"], a["rows_loaded"]) == (3, 3)
    assert a["file_name"] == dl.path.name
    assert a["file_sha256"] == dl.sha256
    assert a["http_status"] == 200
    assert a["finished_at"] is not None and a["error_message"] is None


@integration
def test_series_NA_is_stored_as_the_text_NA(tmp_path, audit_conn, data_conn):
    dl = landed(tmp_path, day_rows(D1, SctySrs="NA"))
    assert load_day(audit_conn, data_conn, DATASET, CFG, dl).status == SUCCESS
    series = fetch(audit_conn, "SELECT DISTINCT series FROM raw.bhavcopy_cm")
    assert [r["series"] for r in series] == ["NA"]


@integration
def test_blank_numeric_loads_as_null_and_numbers_load_exactly(
    tmp_path, audit_conn, data_conn
):
    rows = day_rows(D1, 1, LastPric="", ClsPric="104.10")
    assert (
        load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, rows)).status
        == SUCCESS
    )
    (r,) = fetch(audit_conn, "SELECT last_price, close_price FROM raw.bhavcopy_cm")
    assert r["last_price"] is None
    assert r["close_price"] == Decimal("104.1000")


@integration
def test_triggers_normalise_values_and_rows_land_in_the_right_partition(
    tmp_path, audit_conn, data_conn
):
    rows = [
        row(TradDt=D1.isoformat(), BizDt=D1.isoformat(), TckrSymb="abc", SctySrs="eq")
    ]
    assert (
        load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, rows)).status
        == SUCCESS
    )
    (r,) = fetch(
        audit_conn,
        "SELECT symbol, series, row_hash, loaded_at, tableoid::regclass::text AS part "
        "FROM raw.bhavcopy_cm",
    )
    assert (r["symbol"], r["series"]) == ("ABC", "EQ")
    assert len(r["row_hash"]) == 32 and r["loaded_at"] is not None
    assert r["part"] == "raw.bhavcopy_cm_2025"


@integration
def test_raw_rows_are_immutable(tmp_path, audit_conn, data_conn):
    load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(D1)))
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        audit_conn.execute("UPDATE raw.bhavcopy_cm SET series = 'BE'")


# --- integration: idempotency and replacement ----------------------------------
@integration
def test_reloading_the_same_file_is_idempotent(tmp_path, audit_conn, data_conn):
    dl = landed(tmp_path, day_rows(D1))
    first = load_day(audit_conn, data_conn, DATASET, CFG, dl)
    second = load_day(audit_conn, data_conn, DATASET, CFG, dl)

    assert raw_count(audit_conn) == 3  # not 6
    assert [a["status"] for a in audit(audit_conn)] == ["SUPERSEDED", "SUCCESS"]
    ids = {
        r["load_id"] for r in fetch(audit_conn, "SELECT load_id FROM raw.bhavcopy_cm")
    }
    assert ids == {second.load_id} and first.load_id != second.load_id


@integration
def test_a_corrected_file_replaces_the_old_rows_completely(
    tmp_path, audit_conn, data_conn
):
    load_day(
        audit_conn,
        data_conn,
        DATASET,
        CFG,
        landed(tmp_path, day_rows(D1, 3, ClsPric="104.10")),
    )
    corrected = landed(
        tmp_path, day_rows(D1, 2, ClsPric="110.00"), name="corrected.zip"
    )
    result = load_day(audit_conn, data_conn, DATASET, CFG, corrected)

    assert result.rows_loaded == 2 and raw_count(audit_conn, D1) == 2
    closes = {
        r["close_price"]
        for r in fetch(audit_conn, "SELECT close_price FROM raw.bhavcopy_cm")
    }
    assert closes == {Decimal("110.0000")}


@integration
def test_loading_one_date_never_touches_another(tmp_path, audit_conn, data_conn):
    load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(D1, 3)))
    load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(D2, 2), D2))
    load_day(
        audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(D1, 3))
    )  # reload D1

    assert (raw_count(audit_conn, D1), raw_count(audit_conn, D2)) == (3, 2)
    d2 = [a for a in audit(audit_conn) if a["trade_date"] == D2]
    assert [a["status"] for a in d2] == ["SUCCESS"]  # D2's audit row was not superseded


# --- integration: failures -----------------------------------------------------
@integration
def test_a_file_dated_for_another_day_fails_cleanly(tmp_path, audit_conn, data_conn):
    dl = landed(tmp_path, day_rows(D2), day=D1)  # contents say D2, we asked for D1
    result = load_day(audit_conn, data_conn, DATASET, CFG, dl)

    assert result.status == FAILED and "expected only" in result.error
    assert raw_count(audit_conn) == 0
    (a,) = audit(audit_conn)
    assert a["status"] == "FAILED" and a["finished_at"] is not None
    assert "expected only" in a["error_message"]


@integration
def test_a_corrupt_zip_fails_cleanly(tmp_path, audit_conn, data_conn):
    dl = landed(tmp_path, day_rows(D1))
    dl.path.write_bytes(b"this is not a zip")
    result = load_day(audit_conn, data_conn, DATASET, CFG, dl)
    assert result.status == FAILED and raw_count(audit_conn) == 0
    assert audit(audit_conn)[0]["status"] == "FAILED"


@integration
def test_a_missing_file_on_disk_fails_cleanly(tmp_path, audit_conn, data_conn):
    dl = landed(tmp_path, day_rows(D1))
    dl.path.unlink()
    result = load_day(audit_conn, data_conn, DATASET, CFG, dl)
    assert result.status == FAILED and audit(audit_conn)[0]["status"] == "FAILED"


@integration
def test_the_database_trigger_rejects_a_future_trade_date(
    tmp_path, audit_conn, data_conn
):
    future = date.today() + timedelta(days=5)
    result = load_day(
        audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(future), future)
    )
    assert result.status == FAILED and "future" in result.error
    assert raw_count(audit_conn) == 0


@integration
def test_a_failed_reload_leaves_the_previous_good_load_untouched(
    tmp_path, audit_conn, data_conn
):
    good = load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(D1)))

    # the file parses fine, but COPY fails inside the database AFTER the delete has run
    broken_cfg = {
        **CFG,
        "columns": [
            *CFG["columns"][:-1],
            {"source": "Rmks", "target": "no_such_column", "type": "text"},
        ],
    }
    result = load_day(
        audit_conn, data_conn, DATASET, broken_cfg, landed(tmp_path, day_rows(D1))
    )

    assert result.status == FAILED and "no_such_column" in result.error
    assert raw_count(audit_conn, D1) == 3  # delete was rolled back
    ids = {
        r["load_id"] for r in fetch(audit_conn, "SELECT load_id FROM raw.bhavcopy_cm")
    }
    assert ids == {good.load_id}
    statuses = {a["load_id"]: a["status"] for a in audit(audit_conn)}
    assert statuses[good.load_id] == "SUCCESS"  # not superseded
    assert statuses[result.load_id] == "FAILED"


@integration
def test_a_failed_load_leaves_the_connection_usable_for_the_next_one(
    tmp_path, audit_conn, data_conn
):
    bad = landed(tmp_path, day_rows(D2), day=D1)
    assert load_day(audit_conn, data_conn, DATASET, CFG, bad).status == FAILED
    ok = load_day(
        audit_conn,
        data_conn,
        DATASET,
        CFG,
        landed(tmp_path, day_rows(D1), name="ok.zip"),
    )
    assert ok.status == SUCCESS and raw_count(audit_conn) == 3


@integration
def test_the_data_connection_is_reusable_after_a_database_level_failure(
    tmp_path, audit_conn, data_conn
):
    """A failed COPY must roll back and release locks, or the next load would hang or break."""
    load_day(audit_conn, data_conn, DATASET, CFG, landed(tmp_path, day_rows(D1)))
    broken_cfg = {
        **CFG,
        "columns": [
            *CFG["columns"][:-1],
            {"source": "Rmks", "target": "no_such_column", "type": "text"},
        ],
    }
    failed = load_day(
        audit_conn, data_conn, DATASET, broken_cfg, landed(tmp_path, day_rows(D1))
    )
    assert failed.status == FAILED
    assert (
        data_conn.info.transaction_status == TransactionStatus.IDLE
    )  # nothing left open

    retry = load_day(
        audit_conn,
        data_conn,
        DATASET,
        CFG,
        landed(tmp_path, day_rows(D1), name="r.zip"),
    )
    assert retry.status == SUCCESS and raw_count(audit_conn, D1) == 3


# --- integration: misuse and no-file -------------------------------------------
@integration
def test_load_day_refuses_a_download_with_nothing_to_load(
    tmp_path, audit_conn, data_conn
):
    nothing = DownloadResult(
        dataset=DATASET, trade_date=D1, status=NO_FILE, url="https://x/y"
    )
    with pytest.raises(ValueError, match="nothing to load"):
        load_day(audit_conn, data_conn, DATASET, CFG, nothing)
    assert (
        audit(audit_conn) == []
    )  # no audit row for a call that should not have happened


@integration
def test_an_invalid_target_table_is_rejected_before_anything_is_written(
    tmp_path, audit_conn, data_conn
):
    cfg = {**CFG, "target_table": "raw.bhavcopy_cm; DROP TABLE audit.ingestion_log"}
    with pytest.raises(ValueError, match="target_table"):
        load_day(audit_conn, data_conn, DATASET, cfg, landed(tmp_path, day_rows(D1)))
    assert audit(audit_conn) == []


@integration
def test_connection_modes_are_enforced(tmp_path, audit_conn, data_conn):
    dl = landed(tmp_path, day_rows(D1))
    with pytest.raises(ValueError, match="audit_conn"):
        load_day(data_conn, data_conn, DATASET, CFG, dl)
    with pytest.raises(ValueError, match="data_conn must NOT"):
        load_day(audit_conn, audit_conn, DATASET, CFG, dl)

    data_conn.execute("SELECT 1")  # leaves a transaction open
    with pytest.raises(ValueError, match="open transaction"):
        load_day(audit_conn, data_conn, DATASET, CFG, dl)
    data_conn.rollback()
    assert audit(audit_conn) == []


@integration
def test_record_no_file_writes_an_audit_row_and_no_data(audit_conn):
    dl = DownloadResult(
        dataset=DATASET, trade_date=D1, status=NO_FILE, url="https://x/y",
        http_status=404, error="404 for https://x/y",
    )  # fmt: skip
    first = record_no_file(audit_conn, DATASET, dl)
    second = record_no_file(
        audit_conn, DATASET, dl
    )  # retries must not clash with any index

    assert first.status == NO_FILE and first.load_id != second.load_id
    rows = audit(audit_conn)
    assert [r["status"] for r in rows] == ["NO_FILE", "NO_FILE"]
    assert rows[0]["http_status"] == 404 and rows[0]["finished_at"] is not None
    assert raw_count(audit_conn) == 0


@integration
def test_record_download_failure_writes_a_failed_audit_row(audit_conn):
    dl = DownloadResult(
        dataset=DATASET, trade_date=D1, status="FAILED", url="https://x/y",
        http_status=503, error="gave up after 3 attempts",
    )  # fmt: skip
    result = record_download_failure(audit_conn, DATASET, dl)
    assert result.status == FAILED
    (a,) = audit(audit_conn)
    assert a["status"] == "FAILED" and a["http_status"] == 503
    assert "gave up" in a["error_message"] and a["finished_at"] is not None
