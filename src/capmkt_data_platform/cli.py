"""Command line interface.

    python -m capmkt_data_platform.cli download --date 2026-11-06
    python -m capmkt_data_platform.cli backfill --start 2025-07-01 --end 2026-11-06
    python -m capmkt_data_platform.cli healthcheck
    python -m capmkt_data_platform.cli load-sample

Exit codes (designed for Airflow's BashOperator):
    0   success (downloaded, or a valid cached file was reused)
    99  no file on the server  -> BashOperator marks the task SKIPPED
    1   failure                -> task fails and Airflow retries

The last line printed on stdout is a JSON document, which BashOperator can push to
XCom. Logs go to stderr.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import psycopg
import typer

from capmkt_data_platform.db import connect
from capmkt_data_platform.ingest.loader import (
    SUCCESS,
    load_day,
    record_download_failure,
    record_no_file,
)
from capmkt_data_platform.ingest.nse_client import (
    CACHED,
    DOWNLOADED,
    FAILED,
    NO_FILE,
    NseClient,
    NseError,
    read_csv_member,
)
from capmkt_data_platform.ingest.parser import ParseError, parse_bhavcopy
from capmkt_data_platform.logging_config import configure_logging
from capmkt_data_platform.metadata import MetadataError, load_dataset
from capmkt_data_platform.settings import Settings, get_settings

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_FILE = 99

DATE_FORMAT = "%Y-%m-%d"
log = logging.getLogger(__name__)

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="capmkt data platform CLI"
)


def build_client(settings: Settings) -> NseClient:
    return NseClient(
        settings.landing_dir,
        timeout=settings.http_timeout_seconds,
        max_attempts=settings.http_max_attempts,
        backoff_seconds=settings.http_backoff_seconds,
    )


def _emit(payload: dict) -> None:
    typer.echo(json.dumps(payload, default=str))


# ---------for WSL docker and airflow-----------
def _dsn() -> str:
    return (
        f"host={os.environ.get('PGHOST', 'localhost')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} "
        f"password={os.environ['PGPASSWORD']}"
    )


# ---------for WSL docker and airflow-----------


@app.callback()
def main(
    log_level: Annotated[str, typer.Option("--log-level", envvar="LOG_LEVEL")] = "INFO",
    log_file: Annotated[
        Path | None, typer.Option("--log-file", help="Optional log file path")
    ] = None,
) -> None:
    configure_logging(log_level, log_file)


@app.command()
def parse(
    zip_file: Annotated[Path, typer.Argument(help="Landed bhavcopy zip")],
    trade_date: Annotated[datetime, typer.Option("--date", formats=[DATE_FORMAT])],
    dataset: Annotated[str, typer.Option("--dataset")] = "bhavcopy_cm",
) -> None:
    """Validate a landed file and print row counts. Writes nothing."""
    settings = get_settings()
    try:
        cfg = load_dataset(settings.datasets_file, dataset)
        parsed = parse_bhavcopy(read_csv_member(zip_file), cfg, trade_date.date())
    except (MetadataError, ParseError, NseError) as exc:
        log.error("%s", exc)
        raise typer.Exit(EXIT_FAILED) from exc
    _emit({"columns": len(parsed.columns), "rows": parsed.row_count})


@app.command()
def download(
    trade_date: Annotated[
        datetime, typer.Option("--date", formats=[DATE_FORMAT], help="YYYY-MM-DD")
    ],
    dataset: Annotated[str, typer.Option("--dataset")] = "bhavcopy_cm",
    force: Annotated[
        bool, typer.Option("--force", help="Re-download even if a valid file exists")
    ] = False,
    fail_on_missing: Annotated[
        bool,
        typer.Option(
            "--fail-on-missing",
            help="Exit 1 (retry) instead of 99 (skip) when the file is missing. "
            "Use in Airflow for days already known to be trading days.",
        ),
    ] = False,
) -> None:
    """Download one day's file into data/landing/<dataset>/."""
    settings = get_settings()
    try:
        cfg = load_dataset(settings.datasets_file, dataset)
    except MetadataError as exc:
        log.error("%s", exc)
        raise typer.Exit(EXIT_FAILED) from exc

    client = build_client(settings)
    result = client.download_day(
        dataset, cfg["url_template"], trade_date.date(), force=force
    )
    _emit(result.to_dict())

    if result.status in (DOWNLOADED, CACHED):
        raise typer.Exit(EXIT_OK)
    if result.status == NO_FILE:
        raise typer.Exit(EXIT_FAILED if fail_on_missing else EXIT_NO_FILE)
    raise typer.Exit(EXIT_FAILED)


@app.command()
def backfill(
    start: Annotated[datetime, typer.Option("--start", formats=[DATE_FORMAT])],
    end: Annotated[datetime, typer.Option("--end", formats=[DATE_FORMAT])],
    dataset: Annotated[str, typer.Option("--dataset")] = "bhavcopy_cm",
    pause: Annotated[
        float | None, typer.Option("--pause", help="Seconds between requests")
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    include_weekends: Annotated[
        bool,
        typer.Option(
            "--include-weekends",
            help="Also try Saturdays and Sundays (special sessions)",
        ),
    ] = False,
) -> None:
    """Download every weekday in a date range. Holidays show up as NO_FILE, which is fine."""
    settings = get_settings()
    try:
        cfg = load_dataset(settings.datasets_file, dataset)
    except MetadataError as exc:
        log.error("%s", exc)
        raise typer.Exit(EXIT_FAILED) from exc

    client = build_client(settings)
    results = client.backfill(
        dataset,
        cfg["url_template"],
        start.date(),
        end.date(),
        pause=settings.request_pause_seconds if pause is None else pause,
        force=force,
        include_weekends=include_weekends,
    )
    counts = Counter(r.status for r in results)
    failed_dates = [r.trade_date.isoformat() for r in results if r.status == FAILED]
    _emit({"dataset": dataset, "counts": dict(counts), "failed_dates": failed_dates})
    raise typer.Exit(EXIT_FAILED if failed_dates else EXIT_OK)


@app.command()
def ingest(
    trade_date: Annotated[
        datetime, typer.Option("--date", formats=[DATE_FORMAT], help="YYYY-MM-DD")
    ],
    dataset: Annotated[str, typer.Option("--dataset")] = "bhavcopy_cm",
    force: Annotated[
        bool, typer.Option("--force", help="Re-download even if a file exists")
    ] = False,
    fail_on_missing: Annotated[
        bool,
        typer.Option(
            "--fail-on-missing",
            help="Exit 1 (retry) instead of 99 (skip) when the file is missing.",
        ),
    ] = False,
) -> None:
    """Download one day's file (if needed) and load it into the raw table."""
    settings = get_settings()
    try:
        cfg = load_dataset(settings.datasets_file, dataset)
    except MetadataError as exc:
        log.error("%s", exc)
        raise typer.Exit(EXIT_FAILED) from exc

    download_res = build_client(settings).download_day(
        dataset, cfg["url_template"], trade_date.date(), force=force
    )

    audit_conn = data_conn = None
    try:
        audit_conn = connect(settings, autocommit=True)
        if download_res.status == NO_FILE:
            load = record_no_file(audit_conn, dataset, download_res)
        elif download_res.status == FAILED:
            load = record_download_failure(audit_conn, dataset, download_res)
        else:  # DOWNLOADED or CACHED
            data_conn = connect(settings)
            load = load_day(audit_conn, data_conn, dataset, cfg, download_res)
    except (
        psycopg.Error,
        RuntimeError,
    ) as exc:  # database unreachable, or no PGPASSWORD
        log.error("database error: %s", exc)
        _emit({"download": download_res.to_dict(), "load": None, "error": str(exc)})
        raise typer.Exit(EXIT_FAILED) from exc
    finally:
        for conn in (data_conn, audit_conn):
            if conn is not None:
                conn.close()

    _emit({"download": download_res.to_dict(), "load": load.to_dict()})
    if load.status == SUCCESS:
        raise typer.Exit(EXIT_OK)
    if download_res.status == NO_FILE:
        raise typer.Exit(EXIT_FAILED if fail_on_missing else EXIT_NO_FILE)
    raise typer.Exit(EXIT_FAILED)


# ---------for WSL docker and airflow-----------
@app.command()
def healthcheck() -> None:
    """Connect to Postgres, print schema and row counts. Exit 1 on failure."""
    try:
        with psycopg.connect(_dsn(), connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(
                "select count(*) from information_schema.schemata "
                "where schema_name in ('raw','audit','ref','stg','core')"
            )
            schemas = cur.fetchone()[0]
            cur.execute("select count(*) from raw.bhavcopy_cm")
            rows = cur.fetchone()[0]
    except Exception as exc:
        typer.echo(f"UNHEALTHY: {exc}", err=True)
        raise typer.Exit(code=EXIT_FAILED) from exc
    typer.echo(f"OK schemas={schemas} raw.bhavcopy_cm rows={rows}")


@app.command("load-sample")
def load_sample() -> None:
    """Stand-in ingest job: idempotently loads 3 sample rows for a fixed past date."""
    sample_date = date(2026, 11, 13)
    rows = [
        ("AAA", 100, 110, 95, 105, 100),
        ("BBB", 50, 52, 49, 51, 50),
        ("CCC", 200, 210, 198, 205, 199),
    ]
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("delete from raw.bhavcopy_cm where trade_date = %s", (sample_date,))
        cur.execute(
            "update audit.ingestion_log set status = 'SUPERSEDED' "
            "where dataset = 'sample' and trade_date = %s and status = 'SUCCESS'",
            (sample_date,),
        )
        cur.execute(
            "insert into audit.ingestion_log (dataset, trade_date, source_url, status, rows_loaded, finished_at) "
            "values ('sample', %s, 'local://sample', 'SUCCESS', %s, now()) returning load_id",
            (sample_date, len(rows)),
        )
        load_id = cur.fetchone()[0]
        cur.executemany(
            "insert into raw.bhavcopy_cm (load_id, trade_date, symbol, series, open_price, high_price, "
            "low_price, close_price, prev_close_price) values (%s, %s, %s, 'EQ', %s, %s, %s, %s, %s)",
            [(load_id, sample_date, *r) for r in rows],
        )
    typer.echo(f"loaded {len(rows)} sample rows, load_id={load_id}")


# ---------for WSL docker and airflow-----------

if __name__ == "__main__":
    app()
