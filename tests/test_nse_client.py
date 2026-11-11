"""Tests for the NSE client. No test touches the network: a fake session stands in."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import date

import pytest
import requests

from capmkt_data_platform.ingest.nse_client import (
    CACHED,
    DOWNLOADED,
    FAILED,
    HOME_URL,
    NO_FILE,
    DownloadError,
    InvalidFileError,
    NoFileError,
    NseClient,
    build_url,
    iter_weekdays,
    read_csv_member,
    validate_zip,
)

TEMPLATE = "https://example.test/content/cm/Bhav_{yyyymmdd}.csv.zip"
FRIDAY = date(2026, 11, 6)
EMPTY_ZIP = b"PK\x05\x06" + b"\x00" * 18  # the 22-byte empty archive


def make_zip(
    name: str = "Bhav.csv", data: bytes = b"TradDt,SctySrs\n2026-11-06,NA\n"
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, data)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Routes by URL. Each URL has a queue of responses (or exceptions) used in order."""

    def __init__(self, routes: dict[str, list] | None = None) -> None:
        self.routes = {url: list(items) for url, items in (routes or {}).items()}
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        self.calls.append(url)
        queue = self.routes.get(url)
        if not queue:
            return FakeResponse(200, b"")  # e.g. the cookie warm-up page
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def sleeps() -> list[float]:
    return []


def make_client(tmp_path, session, sleeps, **kw) -> NseClient:
    return NseClient(
        tmp_path / "landing",
        session=session,
        sleep=sleeps.append,
        backoff_seconds=1.0,
        **kw,
    )


URL_FRI = build_url(TEMPLATE, FRIDAY)


# --- pure helpers ----------------------------------------------------------
def test_build_url():
    assert (
        build_url(TEMPLATE, FRIDAY)
        == "https://example.test/content/cm/Bhav_20261106.csv.zip"
    )


def test_iter_weekdays_skips_weekends():
    days = list(iter_weekdays(date(2026, 11, 6), date(2026, 11, 10)))
    assert days == [date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 10)]


def test_iter_weekdays_rejects_reversed_range():
    with pytest.raises(ValueError):
        list(iter_weekdays(date(2026, 11, 10), date(2026, 11, 6)))


def test_validate_zip_returns_csv_member_name():
    assert validate_zip(make_zip(name="anything_at_all.csv")) == "anything_at_all.csv"


def test_validate_zip_empty_archive_means_no_file():
    with pytest.raises(NoFileError):
        validate_zip(EMPTY_ZIP)


def test_validate_zip_rejects_non_zip_bytes():
    with pytest.raises(InvalidFileError):
        validate_zip(b"<html>Access Denied</html>")


def test_validate_zip_without_csv_means_no_file():
    with pytest.raises(NoFileError):
        validate_zip(make_zip(name="readme.txt"))


# --- fetch: HTTP behaviour -------------------------------------------------
def test_fetch_404_raises_no_file(tmp_path, sleeps):
    session = FakeSession({URL_FRI: [FakeResponse(404)]})
    client = make_client(tmp_path, session, sleeps)
    with pytest.raises(NoFileError) as exc:
        client.fetch(URL_FRI)
    assert exc.value.http_status == 404
    assert session.calls == [URL_FRI]  # a 404 is not retried


def test_fetch_403_warms_up_then_succeeds(tmp_path, sleeps):
    body = make_zip()
    session = FakeSession({URL_FRI: [FakeResponse(403), FakeResponse(200, body)]})
    client = make_client(tmp_path, session, sleeps)
    assert client.fetch(URL_FRI) == body
    assert session.calls == [URL_FRI, HOME_URL, URL_FRI]  # warm-up only after the 403
    assert sleeps == [1.0]


def test_fetch_retries_network_error(tmp_path, sleeps):
    body = make_zip()
    session = FakeSession(
        {URL_FRI: [requests.ConnectionError("boom"), FakeResponse(200, body)]}
    )
    client = make_client(tmp_path, session, sleeps)
    assert client.fetch(URL_FRI) == body


def test_fetch_gives_up_with_exponential_backoff(tmp_path, sleeps):
    session = FakeSession({URL_FRI: [FakeResponse(500)] * 3})
    client = make_client(tmp_path, session, sleeps, max_attempts=3)
    with pytest.raises(DownloadError) as exc:
        client.fetch(URL_FRI)
    assert exc.value.http_status == 500
    assert session.calls.count(URL_FRI) == 3
    assert sleeps == [1.0, 2.0]  # no sleep after the final attempt


def test_fetch_unexpected_status_fails_fast(tmp_path, sleeps):
    session = FakeSession({URL_FRI: [FakeResponse(418)]})
    client = make_client(tmp_path, session, sleeps)
    with pytest.raises(DownloadError):
        client.fetch(URL_FRI)
    assert session.calls == [URL_FRI]


# --- download_day: disk behaviour -----------------------------------------
def test_download_day_lands_file_with_checksum(tmp_path, sleeps):
    body = make_zip()
    client = make_client(
        tmp_path, FakeSession({URL_FRI: [FakeResponse(200, body)]}), sleeps
    )
    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)

    assert res.status == DOWNLOADED
    assert res.path == tmp_path / "landing" / "bhavcopy_cm" / "Bhav_20261106.csv.zip"
    assert res.path.read_bytes() == body
    assert res.sha256 == hashlib.sha256(body).hexdigest()
    assert res.size_bytes == len(body)
    assert not list(res.path.parent.glob("*.part"))  # no temp file left behind


def test_download_day_reuses_valid_cache(tmp_path, sleeps):
    body = make_zip()
    session = FakeSession({URL_FRI: [FakeResponse(200, body)]})
    client = make_client(tmp_path, session, sleeps)
    client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    second = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)

    assert second.status == CACHED
    assert session.calls.count(URL_FRI) == 1  # no second request


def test_download_day_force_redownloads(tmp_path, sleeps):
    body = make_zip()
    session = FakeSession({URL_FRI: [FakeResponse(200, body), FakeResponse(200, body)]})
    client = make_client(tmp_path, session, sleeps)
    client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    again = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY, force=True)

    assert again.status == DOWNLOADED
    assert session.calls.count(URL_FRI) == 2


def test_download_day_missing_file_is_no_file(tmp_path, sleeps):
    client = make_client(tmp_path, FakeSession({URL_FRI: [FakeResponse(404)]}), sleeps)
    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    assert res.status == NO_FILE
    assert res.http_status == 404
    assert res.path is None


def test_download_day_empty_zip_is_no_file_and_not_saved(tmp_path, sleeps):
    client = make_client(
        tmp_path, FakeSession({URL_FRI: [FakeResponse(200, EMPTY_ZIP)]}), sleeps
    )
    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    assert res.status == NO_FILE
    assert not (tmp_path / "landing").exists()


def test_download_day_html_error_page_is_failed_and_not_saved(tmp_path, sleeps):
    html = b"<html>Access Denied</html>"
    client = make_client(
        tmp_path, FakeSession({URL_FRI: [FakeResponse(200, html)]}), sleeps
    )
    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    assert res.status == FAILED
    assert not (tmp_path / "landing").exists()


def test_download_day_server_errors_are_failed_and_write_nothing(tmp_path, sleeps):
    session = FakeSession({URL_FRI: [FakeResponse(503)] * 3})
    client = make_client(tmp_path, session, sleeps)
    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    assert res.status == FAILED
    assert res.http_status == 503
    assert not (tmp_path / "landing").exists()


def test_corrupt_cached_file_is_redownloaded(tmp_path, sleeps):
    body = make_zip()
    bad = tmp_path / "landing" / "bhavcopy_cm" / "Bhav_20261106.csv.zip"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"garbage")
    client = make_client(
        tmp_path, FakeSession({URL_FRI: [FakeResponse(200, body)]}), sleeps
    )

    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    assert res.status == DOWNLOADED
    assert bad.read_bytes() == body


def test_result_to_dict_is_json_friendly(tmp_path, sleeps):
    client = make_client(tmp_path, FakeSession({URL_FRI: [FakeResponse(404)]}), sleeps)
    data = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY).to_dict()
    assert data["trade_date"] == "2026-11-06"
    assert data["path"] is None


# --- backfill --------------------------------------------------------------
def test_backfill_skips_weekends_and_continues_past_missing_days(tmp_path, sleeps):
    body = make_zip()
    mon = build_url(TEMPLATE, date(2026, 11, 9))
    tue = build_url(TEMPLATE, date(2026, 11, 10))
    session = FakeSession(
        {
            URL_FRI: [FakeResponse(200, body)],
            mon: [FakeResponse(404)],
            tue: [FakeResponse(200, body)],
        }
    )
    client = make_client(tmp_path, session, sleeps)
    results = client.backfill(
        "bhavcopy_cm", TEMPLATE, FRIDAY, date(2026, 11, 10), pause=0
    )

    assert [r.status for r in results] == [DOWNLOADED, NO_FILE, DOWNLOADED]
    assert len(session.calls) == 3  # Saturday and Sunday were never requested


def test_backfill_second_run_uses_cache(tmp_path, sleeps):
    body = make_zip()
    session = FakeSession({URL_FRI: [FakeResponse(200, body)]})
    client = make_client(tmp_path, session, sleeps)
    client.backfill("bhavcopy_cm", TEMPLATE, FRIDAY, FRIDAY, pause=0)
    again = client.backfill("bhavcopy_cm", TEMPLATE, FRIDAY, FRIDAY, pause=0)
    assert [r.status for r in again] == [CACHED]


# --- reading back for Day 5 ------------------------------------------------
def test_read_csv_member_returns_csv_bytes_and_keeps_na_text(tmp_path, sleeps):
    body = make_zip(data=b"TradDt,SctySrs\n2026-11-06,NA\n")
    client = make_client(
        tmp_path, FakeSession({URL_FRI: [FakeResponse(200, body)]}), sleeps
    )
    res = client.download_day("bhavcopy_cm", TEMPLATE, FRIDAY)
    assert read_csv_member(res.path) == b"TradDt,SctySrs\n2026-11-06,NA\n"
