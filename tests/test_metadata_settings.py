from __future__ import annotations

from pathlib import Path

import pytest

from capmkt_data_platform.metadata import MetadataError, load_dataset
from capmkt_data_platform.settings import PROJECT_ROOT, Settings

VALID = """
datasets:
  bhavcopy_cm:
    url_template: "https://x/Bhav_{yyyymmdd}.csv.zip"
  broken:
    url_template: "https://x/no_placeholder.zip"
"""


def write(tmp_path, text: str) -> Path:
    path = tmp_path / "datasets.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_dataset_returns_config(tmp_path):
    cfg = load_dataset(write(tmp_path, VALID), "bhavcopy_cm")
    assert cfg["url_template"].endswith("{yyyymmdd}.csv.zip")


def test_unknown_dataset_raises(tmp_path):
    with pytest.raises(MetadataError):
        load_dataset(write(tmp_path, VALID), "missing")


def test_url_template_without_placeholder_raises(tmp_path):
    with pytest.raises(MetadataError):
        load_dataset(write(tmp_path, VALID), "broken")


def test_missing_file_raises(tmp_path):
    with pytest.raises(MetadataError):
        load_dataset(tmp_path / "nope.yml", "bhavcopy_cm")


def test_relative_paths_resolve_against_project_root_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # a different working directory must not matter
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("DATASETS_FILE", raising=False)
    s = Settings(_env_file=None)
    assert s.data_dir == (PROJECT_ROOT / "data").resolve()
    assert s.landing_dir == s.data_dir / "landing"
    assert s.datasets_file == (PROJECT_ROOT / "config" / "datasets.yml").resolve()


def test_env_var_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "elsewhere"))
    assert Settings(_env_file=None).data_dir == tmp_path / "elsewhere"
