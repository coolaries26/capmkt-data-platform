"""NSE archive downloader.

Design rules:
* No work at import time (no logging config, no directories, no network).
* download_day() never raises for expected outcomes. It returns a DownloadResult
  with a status, so callers (CLI, Airflow, the Day 5 loader) can record an audit row.
* The landing zip is the system of record. We keep it as downloaded and let the
  loader read the CSV straight out of it, so there is no "extracted" copy to drift.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import random
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

HOME_URL = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports",
    # No Accept-Encoding override: requests advertises only encodings it can decode.
}

# Result statuses
DOWNLOADED = "DOWNLOADED"
CACHED = "CACHED"  # valid file already on disk, nothing fetched
NO_FILE = "NO_FILE"  # holiday, weekend, or not yet published
FAILED = "FAILED"  # network or server trouble, or a corrupt file


# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------
class NseError(Exception):
    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class NoFileError(NseError):
    """The file does not exist (404) or the archive holds no CSV (empty zip)."""


class TransientHTTPError(NseError):
    """Retryable HTTP failure (403, 429, 5xx)."""


class DownloadError(NseError):
    """Gave up after retries, or got an unexpected HTTP status."""


class InvalidFileError(NseError):
    """Bytes received are not a valid zip archive."""


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------
def build_url(url_template: str, trade_date: date) -> str:
    return url_template.format(yyyymmdd=trade_date.strftime("%Y%m%d"))


def iter_weekdays(start: date, end: date) -> Iterator[date]:
    """Yield Monday to Friday dates in [start, end]. Exchange holidays still yield
    NO_FILE results; a holiday calendar (Week 2) will remove those requests."""
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def validate_zip(content: bytes) -> str:
    """Return the name of the CSV inside the zip.

    Raises InvalidFileError for non-zip bytes and NoFileError for an archive with
    no CSV (this includes the 22-byte empty archive).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            csv_names = [
                info.filename
                for info in zf.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".csv")
            ]
    except zipfile.BadZipFile as exc:
        raise InvalidFileError("content is not a valid zip archive") from exc
    if not csv_names:
        raise NoFileError("zip archive contains no CSV", http_status=200)
    return csv_names[0]  # never hardcode the member name


def read_csv_member(zip_path: Path) -> bytes:
    """Return the CSV bytes from a landed zip (used by the Day 5 parser)."""
    content = zip_path.read_bytes()
    name = validate_zip(content)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return zf.read(name)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ----------------------------------------------------------------------------
# Result object
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class DownloadResult:
    dataset: str
    trade_date: date
    status: str
    url: str
    path: Path | None = None
    http_status: int | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trade_date"] = self.trade_date.isoformat()
        data["path"] = str(self.path) if self.path else None
        return data


# ----------------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------------
class NseClient:
    def __init__(
        self,
        landing_dir: Path,
        *,
        session: requests.Session | Any | None = None,
        timeout: float = 60.0,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.landing_dir = Path(landing_dir)
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self.session = session if session is not None else requests.Session()
        self.session.headers.update(HEADERS)

    # -- network ----------------------------------------------------------
    def _warm_up(self) -> None:
        """Visit the NSE home page to pick up cookies. Done only after a 403/429."""
        try:
            self.session.get(HOME_URL, timeout=self.timeout)
        except requests.RequestException as exc:
            log.warning("cookie warm-up failed: %s", exc)

    def fetch(self, url: str) -> bytes:
        """GET a URL with retries. Raises NoFileError on 404, DownloadError on give-up."""
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                log.warning(
                    "attempt %d/%d network error: %s", attempt, self.max_attempts, exc
                )
            else:
                status = resp.status_code
                if status == 200:
                    return resp.content
                if status == 404:
                    raise NoFileError(f"404 for {url}", http_status=404)
                if status in (403, 429) or status >= 500:
                    last_error = TransientHTTPError(
                        f"HTTP {status} for {url}", http_status=status
                    )
                    log.warning(
                        "attempt %d/%d got HTTP %d", attempt, self.max_attempts, status
                    )
                    if status in (403, 429):
                        self._warm_up()
                else:
                    raise DownloadError(
                        f"unexpected HTTP {status} for {url}", http_status=status
                    )

            if attempt < self.max_attempts:
                self._sleep(self.backoff_seconds * 2 ** (attempt - 1))

        raise DownloadError(
            f"gave up after {self.max_attempts} attempts: {last_error}",
            http_status=getattr(last_error, "http_status", None),
        ) from last_error

    # -- disk -------------------------------------------------------------
    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        """Write via a .part file and rename, so a crash never leaves a half file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        try:
            tmp.write_bytes(content)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _local_path(self, dataset: str, url: str) -> Path:
        return self.landing_dir / dataset / Path(urlparse(url).path).name

    # -- public API -------------------------------------------------------
    def download_day(
        self,
        dataset: str,
        url_template: str,
        trade_date: date,
        *,
        force: bool = False,
    ) -> DownloadResult:
        url = build_url(url_template, trade_date)
        path = self._local_path(dataset, url)

        def result(status: str, **kw: Any) -> DownloadResult:
            return DownloadResult(
                dataset=dataset, trade_date=trade_date, status=status, url=url, **kw
            )

        # 1) reuse a valid file already on disk (idempotent, resumable backfills)
        if path.exists() and not force:
            try:
                content = path.read_bytes()
                validate_zip(content)
                log.info("[%s] cached: %s", trade_date, path)
                return result(
                    CACHED, path=path, size_bytes=len(content), sha256=_sha256(content)
                )
            except (NseError, OSError) as exc:
                log.warning(
                    "[%s] cached file unusable (%s), re-downloading", trade_date, exc
                )

        # 2) download and validate
        try:
            content = self.fetch(url)
            validate_zip(content)
        except NoFileError as exc:
            log.info("[%s] no file: %s", trade_date, exc)
            return result(NO_FILE, http_status=exc.http_status, error=str(exc))
        except (DownloadError, InvalidFileError) as exc:
            log.error("[%s] failed: %s", trade_date, exc)
            return result(FAILED, http_status=exc.http_status, error=str(exc))

        # 3) land it
        self._atomic_write(path, content)
        log.info("[%s] downloaded %d bytes -> %s", trade_date, len(content), path)
        return result(
            DOWNLOADED,
            path=path,
            http_status=200,
            size_bytes=len(content),
            sha256=_sha256(content),
        )

    def backfill(
        self,
        dataset: str,
        url_template: str,
        start: date,
        end: date,
        *,
        pause: float = 1.0,
        force: bool = False,
    ) -> list[DownloadResult]:
        results: list[DownloadResult] = []
        for day in iter_weekdays(start, end):
            res = self.download_day(dataset, url_template, day, force=force)
            results.append(res)
            if res.status != CACHED and pause > 0:
                self._sleep(pause + random.uniform(0, pause / 2))  # be polite to NSE
        return results
