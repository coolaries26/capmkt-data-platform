"""Load one landed bhavcopy file into the raw table, with a complete audit trail.

Two connections, on purpose:

* audit_conn (autocommit)  - writes audit.ingestion_log rows. They are committed at once,
  so a failed data load still leaves a record of what happened.
* data_conn (normal)       - runs ONE transaction per load: supersede the previous
  SUCCESS row, delete the date, COPY the new rows, verify the count, mark SUCCESS.
  Any failure rolls all of that back, so the previous good load is never damaged.

Reloading a date is therefore idempotent: the same file gives the same rows, and a
corrected file replaces the old rows completely.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

from capmkt_data_platform.ingest.nse_client import (
    CACHED,
    DOWNLOADED,
    NO_FILE,
    DownloadResult,
    NseError,
    read_csv_member,
)
from capmkt_data_platform.ingest.parser import ParsedFile, ParseError, parse_bhavcopy

log = logging.getLogger(__name__)

SUCCESS = "SUCCESS"
FAILED = "FAILED"
_MAX_ERROR_CHARS = 2000
_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


class LoadError(RuntimeError):
    """The load ran but its result failed a sanity check."""


@dataclass(frozen=True)
class LoadResult:
    load_id: int
    status: str  # SUCCESS | FAILED | NO_FILE
    rows_loaded: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _table_identifier(name: str) -> sql.Identifier:
    """'raw.bhavcopy_cm' -> "raw"."bhavcopy_cm". Rejects anything that is not schema.table."""
    if not _TABLE_RE.match(name):
        raise ValueError(
            f"invalid target_table '{name}' (expected schema.table, lower case)"
        )
    return sql.Identifier(*name.split("."))


def _check_connections(
    audit_conn: psycopg.Connection, data_conn: psycopg.Connection
) -> None:
    if not audit_conn.autocommit:
        raise ValueError("audit_conn must be in autocommit mode")
    if data_conn.autocommit:
        raise ValueError("data_conn must NOT be in autocommit mode")
    if data_conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("data_conn has an open transaction; commit or roll back first")


def _start_audit_row(
    audit_conn: psycopg.Connection, dataset: str, download: DownloadResult
) -> int:
    row = audit_conn.execute(
        """
        INSERT INTO audit.ingestion_log
            (dataset, trade_date, source_url, http_status, file_name, file_sha256)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING load_id
        """,
        (
            dataset,
            download.trade_date,
            download.url,
            download.http_status,
            download.path.name if download.path else None,
            download.sha256,
        ),
    ).fetchone()
    return int(row[0])


def _mark_failed(audit_conn: psycopg.Connection, load_id: int, message: str) -> None:
    audit_conn.execute(
        """
        UPDATE audit.ingestion_log
           SET status = 'FAILED', error_message = %s, finished_at = now()
         WHERE load_id = %s
        """,
        (message[:_MAX_ERROR_CHARS], load_id),
    )


def _replace_day(
    conn: psycopg.Connection,
    table: sql.Identifier,
    dataset: str,
    trade_date: date,
    load_id: int,
    parsed: ParsedFile,
) -> int:
    """Swap one trade date's rows inside a single transaction. Returns the loaded row count."""
    columns = ["load_id", *parsed.columns]
    copy_stmt = sql.SQL("COPY {table} ({cols}) FROM STDIN").format(
        table=table, cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    )
    try:
        with conn.cursor() as cur:
            # Serialise concurrent loads of the same dataset and date (released at commit)
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{dataset}:{trade_date.isoformat()}",),
            )
            # Free the "one SUCCESS per date" slot before the new row claims it
            cur.execute(
                """
                UPDATE audit.ingestion_log SET status = 'SUPERSEDED'
                 WHERE dataset = %s AND trade_date = %s AND status = 'SUCCESS'
                """,
                (dataset, trade_date),
            )
            cur.execute(
                sql.SQL("DELETE FROM {table} WHERE trade_date = %s").format(
                    table=table
                ),
                (trade_date,),
            )
            with cur.copy(copy_stmt) as copy:
                for values in parsed.rows:
                    copy.write_row((load_id, *values))

            cur.execute(
                sql.SQL("SELECT count(*) FROM {table} WHERE load_id = %s").format(
                    table=table
                ),
                (load_id,),
            )
            loaded = int(cur.fetchone()[0])
            if loaded != parsed.row_count:
                raise LoadError(
                    f"loaded {loaded} rows but the file has {parsed.row_count}"
                )

            cur.execute(
                """
                UPDATE audit.ingestion_log
                   SET status = 'SUCCESS', rows_in_file = %s, rows_loaded = %s,
                       finished_at = now(), error_message = NULL
                 WHERE load_id = %s
                """,
                (parsed.row_count, loaded, load_id),
            )
        conn.commit()
    except BaseException:
        conn.rollback()  # undo supersede + delete + copy together
        raise
    return loaded


# ----------------------------------------------------------------------------
# public API
# ----------------------------------------------------------------------------
def load_day(
    audit_conn: psycopg.Connection,
    data_conn: psycopg.Connection,
    dataset: str,
    cfg: dict[str, Any],
    download: DownloadResult,
) -> LoadResult:
    """Load a landed file. Never raises for bad data: the outcome is in the LoadResult
    and in audit.ingestion_log. Raises ValueError for misuse (wrong status/connections)."""
    if download.status not in (DOWNLOADED, CACHED) or download.path is None:
        raise ValueError(f"nothing to load: download status is {download.status}")
    _check_connections(audit_conn, data_conn)
    table = _table_identifier(cfg["target_table"])

    load_id = _start_audit_row(audit_conn, dataset, download)
    log.info(
        "[%s] load %d started (%s)", download.trade_date, load_id, download.path.name
    )
    try:
        parsed = parse_bhavcopy(
            read_csv_member(download.path), cfg, download.trade_date
        )
        loaded = _replace_day(
            data_conn, table, dataset, download.trade_date, load_id, parsed
        )
    except Exception as exc:  # every failure must end up as a FAILED audit row
        message = f"{type(exc).__name__}: {exc}"
        expected = (ParseError, NseError, OSError, psycopg.Error, LoadError)
        if isinstance(exc, expected):
            log.error("[%s] load %d failed: %s", download.trade_date, load_id, message)
        else:
            log.exception("[%s] load %d crashed", download.trade_date, load_id)
        _mark_failed(audit_conn, load_id, message)
        return LoadResult(load_id, FAILED, error=message[:_MAX_ERROR_CHARS])

    log.info("[%s] load %d done: %d rows", download.trade_date, load_id, loaded)
    return LoadResult(load_id, SUCCESS, rows_loaded=loaded)


def _record_without_file(
    audit_conn: psycopg.Connection, dataset: str, download: DownloadResult, status: str
) -> LoadResult:
    if not audit_conn.autocommit:
        raise ValueError("audit_conn must be in autocommit mode")
    row = audit_conn.execute(
        """
        INSERT INTO audit.ingestion_log
            (dataset, trade_date, source_url, http_status, status, error_message, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        RETURNING load_id
        """,
        (
            dataset,
            download.trade_date,
            download.url,
            download.http_status,
            status,
            (download.error or "")[:_MAX_ERROR_CHARS] or None,
        ),
    ).fetchone()
    return LoadResult(int(row[0]), status, error=download.error)


def record_no_file(
    audit_conn: psycopg.Connection, dataset: str, download: DownloadResult
) -> LoadResult:
    """Audit row for a day with no file (holiday, weekend, or not yet published)."""
    return _record_without_file(audit_conn, dataset, download, NO_FILE)


def record_download_failure(
    audit_conn: psycopg.Connection, dataset: str, download: DownloadResult
) -> LoadResult:
    """Audit row for a download that failed (network, server error, corrupt file)."""
    return _record_without_file(audit_conn, dataset, download, FAILED)
