"""Command line interface.

    python -m capmkt_data_platform.cli download --date 2026-11-06
    python -m capmkt_data_platform.cli backfill --start 2025-07-01 --end 2026-11-06

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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from capmkt_data_platform.ingest.nse_client import (
    CACHED,
    DOWNLOADED,
    FAILED,
    NO_FILE,
    NseClient,
)
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


@app.callback()
def main(
    log_level: Annotated[str, typer.Option("--log-level", envvar="LOG_LEVEL")] = "INFO",
    log_file: Annotated[
        Path | None, typer.Option("--log-file", help="Optional log file path")
    ] = None,
) -> None:
    configure_logging(log_level, log_file)


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
    )
    counts = Counter(r.status for r in results)
    failed_dates = [r.trade_date.isoformat() for r in results if r.status == FAILED]
    _emit({"dataset": dataset, "counts": dict(counts), "failed_dates": failed_dates})
    raise typer.Exit(EXIT_FAILED if failed_dates else EXIT_OK)


if __name__ == "__main__":
    app()
