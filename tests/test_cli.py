"""CLI tests: exit codes and JSON output, which is what Airflow depends on."""

from __future__ import annotations

import json
from datetime import date

import pytest
from typer.testing import CliRunner

from capmkt_data_platform import cli
from capmkt_data_platform.ingest.nse_client import (
    CACHED,
    DOWNLOADED,
    FAILED,
    NO_FILE,
    DownloadResult,
)

runner = CliRunner()


class FakeClient:
    def __init__(self, results: list[DownloadResult]) -> None:
        self.results = results
        self.calls: list[tuple] = []

    def download_day(self, dataset, url_template, trade_date, force=False):
        self.calls.append((dataset, url_template, trade_date, force))
        return self.results[0]

    def backfill(self, dataset, url_template, start, end, **kwargs):
        self.calls.append((dataset, start, end, kwargs))
        return self.results


def result(status: str, day: date = date(2026, 11, 6)) -> DownloadResult:
    return DownloadResult(
        dataset="bhavcopy_cm", trade_date=day, status=status, url="https://x/y"
    )


def last_json(output: str) -> dict:
    lines = [ln for ln in output.splitlines() if ln.strip().startswith("{")]
    return json.loads(lines[-1])


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    cfg = tmp_path / "datasets.yml"
    cfg.write_text(
        'datasets:\n  bhavcopy_cm:\n    url_template: "https://x/Bhav_{yyyymmdd}.csv.zip"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DATASETS_FILE", str(cfg))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def use_client(monkeypatch, *statuses: str) -> FakeClient:
    fake = FakeClient([result(s) for s in statuses])
    monkeypatch.setattr(cli, "build_client", lambda settings: fake)
    return fake


@pytest.mark.parametrize("status", [DOWNLOADED, CACHED])
def test_download_success_exits_zero(monkeypatch, status):
    use_client(monkeypatch, status)
    res = runner.invoke(cli.app, ["download", "--date", "2026-11-06"])
    assert res.exit_code == 0
    assert last_json(res.stdout)["status"] == status


def test_download_missing_file_exits_99_so_airflow_skips(monkeypatch):
    use_client(monkeypatch, NO_FILE)
    res = runner.invoke(cli.app, ["download", "--date", "2026-11-08"])
    assert res.exit_code == 99


def test_download_missing_file_with_fail_on_missing_exits_1(monkeypatch):
    use_client(monkeypatch, NO_FILE)
    res = runner.invoke(
        cli.app, ["download", "--date", "2026-11-06", "--fail-on-missing"]
    )
    assert res.exit_code == 1


def test_download_failure_exits_1(monkeypatch):
    use_client(monkeypatch, FAILED)
    res = runner.invoke(cli.app, ["download", "--date", "2026-11-06"])
    assert res.exit_code == 1


def test_download_passes_date_force_and_url_template(monkeypatch):
    fake = use_client(monkeypatch, DOWNLOADED)
    runner.invoke(cli.app, ["download", "--date", "2026-11-06", "--force"])
    dataset, template, trade_date, force = fake.calls[0]
    assert (dataset, trade_date, force) == ("bhavcopy_cm", date(2026, 11, 6), True)
    assert "{yyyymmdd}" in template


def test_unknown_dataset_exits_1(monkeypatch):
    use_client(monkeypatch, DOWNLOADED)
    res = runner.invoke(
        cli.app, ["download", "--date", "2026-11-06", "--dataset", "nope"]
    )
    assert res.exit_code == 1


def test_bad_date_is_rejected(monkeypatch):
    use_client(monkeypatch, DOWNLOADED)
    res = runner.invoke(cli.app, ["download", "--date", "06/11/2026"])
    assert res.exit_code != 0


def test_backfill_ok_with_missing_days(monkeypatch):
    use_client(monkeypatch, DOWNLOADED, NO_FILE)
    res = runner.invoke(
        cli.app,
        ["backfill", "--start", "2026-11-06", "--end", "2026-11-09", "--pause", "0"],
    )
    assert res.exit_code == 0
    summary = last_json(res.stdout)
    assert summary["counts"] == {DOWNLOADED: 1, NO_FILE: 1}
    assert summary["failed_dates"] == []


def test_backfill_exits_1_when_any_day_failed(monkeypatch):
    use_client(monkeypatch, DOWNLOADED, FAILED)
    res = runner.invoke(
        cli.app,
        ["backfill", "--start", "2026-11-06", "--end", "2026-11-09", "--pause", "0"],
    )
    assert res.exit_code == 1
    assert last_json(res.stdout)["failed_dates"] == ["2026-11-06"]


def test_backfill_passes_include_weekends_flag(monkeypatch):
    fake = use_client(monkeypatch, DOWNLOADED)
    runner.invoke(
        cli.app,
        [
            "backfill",
            "--start",
            "2026-11-06",
            "--end",
            "2026-11-09",
            "--pause",
            "0",
            "--include-weekends",
        ],
    )
    assert fake.calls[0][3]["include_weekends"] is True
