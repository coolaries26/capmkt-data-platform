"""ingest command: exit codes, JSON output and audit rows, against the capmkt_test database."""

from __future__ import annotations

import json
from datetime import date

import pytest
import yaml
from bhavcopy_fixtures import CFG
from test_loader import D1, DATASET, audit, day_rows, landed, raw_count
from typer.testing import CliRunner

from capmkt_data_platform import cli
from capmkt_data_platform.ingest.nse_client import (
    CACHED,
    DOWNLOADED,
    FAILED,
    NO_FILE,
    DownloadResult,
)

pytestmark = pytest.mark.integration
runner = CliRunner()


class FakeClient:
    def __init__(self, result: DownloadResult) -> None:
        self.result = result

    def download_day(self, dataset, url_template, trade_date, force=False):
        return self.result


@pytest.fixture(autouse=True)
def env(
    tmp_path, monkeypatch, audit_conn
):  # audit_conn: skips if no DB, and empties the tables
    cfg = tmp_path / "datasets.yml"
    entry = {**CFG, "url_template": "https://x/Bhav_{yyyymmdd}.csv.zip"}
    cfg.write_text(yaml.safe_dump({"datasets": {DATASET: entry}}), encoding="utf-8")
    monkeypatch.setenv("DATASETS_FILE", str(cfg))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "PGDATABASE", "capmkt_test"
    )  # the CLI must never see the real database


def use(monkeypatch, result: DownloadResult) -> None:
    monkeypatch.setattr(cli, "build_client", lambda settings: FakeClient(result))


def last_json(output: str) -> dict:
    lines = [ln for ln in output.splitlines() if ln.strip().startswith("{")]
    return json.loads(lines[-1])


def args(day: date = D1, *extra: str) -> list[str]:
    return ["ingest", "--date", day.isoformat(), *extra]


@pytest.mark.parametrize("status", [DOWNLOADED, CACHED])
def test_ingest_loads_a_landed_file_and_exits_zero(
    tmp_path, monkeypatch, audit_conn, status
):
    dl = landed(tmp_path, day_rows(D1))
    use(monkeypatch, DownloadResult(**{**dl.__dict__, "status": status}))
    res = runner.invoke(cli.app, args())

    assert res.exit_code == 0, res.output
    out = last_json(res.stdout)
    assert out["load"]["status"] == "SUCCESS" and out["load"]["rows_loaded"] == 3
    assert out["download"]["status"] == status
    assert raw_count(audit_conn, D1) == 3
    assert [a["status"] for a in audit(audit_conn)] == ["SUCCESS"]


def test_ingest_twice_is_idempotent(tmp_path, monkeypatch, audit_conn):
    use(monkeypatch, landed(tmp_path, day_rows(D1)))
    assert runner.invoke(cli.app, args()).exit_code == 0
    assert runner.invoke(cli.app, args()).exit_code == 0
    assert raw_count(audit_conn) == 3
    assert [a["status"] for a in audit(audit_conn)] == ["SUPERSEDED", "SUCCESS"]


def test_missing_file_exits_99_and_writes_a_no_file_audit_row(monkeypatch, audit_conn):
    dl = DownloadResult(
        dataset=DATASET,
        trade_date=D1,
        status=NO_FILE,
        url="https://x/y",
        http_status=404,
    )
    use(monkeypatch, dl)
    res = runner.invoke(cli.app, args())
    assert res.exit_code == 99
    assert [a["status"] for a in audit(audit_conn)] == ["NO_FILE"]


def test_missing_file_with_fail_on_missing_exits_1(monkeypatch, audit_conn):
    dl = DownloadResult(
        dataset=DATASET,
        trade_date=D1,
        status=NO_FILE,
        url="https://x/y",
        http_status=404,
    )
    use(monkeypatch, dl)
    assert runner.invoke(cli.app, args(D1, "--fail-on-missing")).exit_code == 1
    assert [a["status"] for a in audit(audit_conn)] == ["NO_FILE"]


def test_failed_download_exits_1_and_is_audited(monkeypatch, audit_conn):
    dl = DownloadResult(
        dataset=DATASET, trade_date=D1, status=FAILED, url="https://x/y",
        http_status=503, error="gave up after 3 attempts",
    )  # fmt: skip
    use(monkeypatch, dl)
    assert runner.invoke(cli.app, args()).exit_code == 1
    (a,) = audit(audit_conn)
    assert a["status"] == "FAILED" and "gave up" in a["error_message"]


def test_a_file_that_fails_parsing_exits_1_and_loads_nothing(
    tmp_path, monkeypatch, audit_conn
):
    use(
        monkeypatch, landed(tmp_path, day_rows(date(2025, 3, 4)), day=D1)
    )  # wrong date inside
    res = runner.invoke(cli.app, args())
    assert res.exit_code == 1
    assert last_json(res.stdout)["load"]["status"] == "FAILED"
    assert raw_count(audit_conn) == 0
    assert [a["status"] for a in audit(audit_conn)] == ["FAILED"]


def test_unreachable_database_exits_1_with_json(tmp_path, monkeypatch):
    use(monkeypatch, landed(tmp_path, day_rows(D1)))
    monkeypatch.setenv("PGPORT", "1")  # nothing listens here
    res = runner.invoke(cli.app, args())
    assert res.exit_code == 1
    assert "error" in last_json(res.stdout)
