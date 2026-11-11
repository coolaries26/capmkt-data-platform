"""Logging setup. Call configure_logging() from entry points only, never at import time."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    # Logs go to stderr so that stdout stays clean for machine-readable JSON
    # (Airflow's BashOperator can then push the last stdout line to XCom).
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=handlers,
        force=True,  # replace any handlers installed earlier
    )
