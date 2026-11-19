"""Parse a landed bhavcopy CSV into validated rows that are ready for COPY.

Pure function: bytes in, rows out. No database, no filesystem, no network.

Rules:
* Everything is read as text. Pandas never guesses types, and the series code "NA"
  is never turned into a missing value (keep_default_na=False).
* Values stay exactly as NSE published them (strings). We only validate them, so
  PostgreSQL parses numerics exactly, with no float round trip.
* Blank (or whitespace-only) values become None, which COPY loads as NULL.
* All problems found in a file are reported together, so one run shows everything
  that is wrong instead of one error at a time.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

DATE_FORMAT = "%Y-%m-%d"
_PATTERNS = {
    "date": r"\d{4}-\d{2}-\d{2}",
    "numeric": r"-?\d+(\.\d+)?",
    "bigint": r"-?\d+",
}
SUPPORTED_TYPES = {"text", *_PATTERNS}
_MAX_SAMPLES = 3


class ParseError(Exception):
    """The file is unusable: unreadable, wrong shape, wrong date, or bad values."""


@dataclass(frozen=True)
class ParsedFile:
    columns: list[str]  # target (database) column names, in YAML order
    rows: list[tuple]  # str or None per column, same order as `columns`

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _read_csv(csv_bytes: bytes) -> pd.DataFrame:
    try:
        # utf-8-sig drops a byte-order mark if one ever appears in the header
        df = pd.read_csv(
            io.BytesIO(csv_bytes),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise ParseError(f"cannot read CSV: {exc}") from exc
    if df.empty:
        raise ParseError("file has no data rows")
    return df


def _check_header(header: list[str], mapped: list[str], ignored: list[str]) -> None:
    missing = [c for c in mapped if c not in header]
    if missing:
        raise ParseError(f"missing expected column(s): {', '.join(missing)}")
    unknown = [c for c in header if c not in mapped and c not in ignored]
    if unknown:
        # NSE added a column. Not fatal, but someone should decide whether to map it.
        log.warning("unknown column(s) in file, ignored: %s", ", ".join(unknown))


def _type_problem(
    values: pd.Series, col_type: str, source: str, target: str
) -> str | None:
    """Return a description of invalid values, or None if all are valid."""
    if col_type == "text" or values.empty:
        return None
    ok = values.str.fullmatch(_PATTERNS[col_type])
    if col_type == "date":
        ok = ok & pd.to_datetime(values, format=DATE_FORMAT, errors="coerce").notna()
    bad = values[~ok]
    if bad.empty:
        return None
    samples = ", ".join(repr(v) for v in bad.unique()[:_MAX_SAMPLES])
    return (
        f"{source}->{target} ({col_type}): {len(bad)} invalid value(s), e.g. {samples}"
    )


def parse_bhavcopy(
    csv_bytes: bytes, cfg: dict[str, Any], expected_date: date
) -> ParsedFile:
    """Validate a bhavcopy CSV against the dataset metadata and return rows for loading.

    Raises ParseError for problems with the file. Raises ValueError for problems with
    the metadata itself (those are our bugs, not bad data).
    """
    # ---- metadata sanity (our config, not the file) ------------------------------
    columns_cfg = cfg["columns"]
    sources = [c["source"] for c in columns_cfg]
    targets = [c["target"] for c in columns_cfg]
    target_to_source = dict(zip(targets, sources, strict=True))

    for c in columns_cfg:
        if c["type"] not in SUPPORTED_TYPES:
            raise ValueError(f"unsupported type '{c['type']}' for column {c['target']}")
    if "trade_date" not in target_to_source:
        raise ValueError("metadata must map a source column to target 'trade_date'")
    key_targets = list(cfg.get("natural_key", []))
    for t in key_targets:
        if t not in target_to_source:
            raise ValueError(f"natural_key column '{t}' is not a mapped column")

    # ---- read and check the shape ------------------------------------------------
    df = _read_csv(csv_bytes)
    _check_header(list(df.columns), sources, list(cfg.get("ignored_columns", [])))

    # keep mapped columns in YAML order; trim whitespace (blank handling comes later)
    df = df[sources].apply(lambda s: s.str.strip())

    # ---- validate values; collect every problem --------------------------------
    problems: list[str] = []
    for c in columns_cfg:
        col = df[c["source"]]
        problem = _type_problem(col[col.ne("")], c["type"], c["source"], c["target"])
        if problem:
            problems.append(problem)

    date_src = target_to_source["trade_date"]
    found_dates = sorted(set(df[date_src]) - {""})
    if found_dates != [expected_date.isoformat()]:
        problems.append(
            f"{date_src}: expected only {expected_date.isoformat()}, found {found_dates[:5]}"
        )

    key_sources = [target_to_source[t] for t in key_targets]
    for t, src in zip(key_targets, key_sources, strict=True):
        blanks = int(df[src].eq("").sum())
        if blanks:
            problems.append(f"{src}->{t}: {blanks} blank value(s) in key column")
    if key_sources:
        dup_mask = df.duplicated(subset=key_sources, keep=False)
        if dup_mask.any():
            examples = (
                df.loc[dup_mask, key_sources].drop_duplicates().head(_MAX_SAMPLES)
            )
            problems.append(
                f"{int(df.duplicated(subset=key_sources).sum())} duplicate row(s) for key "
                f"{key_targets}, e.g. {examples.values.tolist()}"
            )

    if problems:
        raise ParseError("; ".join(problems))

    # ---- blank -> None, build row tuples -----------------------------------------
    rows = [
        tuple(None if v == "" else v for v in row)
        for row in df.itertuples(index=False, name=None)
    ]
    return ParsedFile(columns=targets, rows=rows)
