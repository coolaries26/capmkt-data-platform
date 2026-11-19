"""Read dataset definitions from config/datasets.yml (the single source of truth)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

URL_PLACEHOLDER = "{yyyymmdd}"


class MetadataError(Exception):
    """datasets.yml is missing, malformed, or lacks a required field."""


def load_dataset(path: Path, name: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except OSError as exc:
        raise MetadataError(f"cannot read {path}: {exc}") from exc

    try:
        cfg = doc["datasets"][name]
    except (KeyError, TypeError) as exc:
        raise MetadataError(f"dataset '{name}' not found in {path}") from exc

    template = cfg.get("url_template") if isinstance(cfg, dict) else None
    if not template or URL_PLACEHOLDER not in template:
        raise MetadataError(
            f"dataset '{name}' needs a url_template containing {URL_PLACEHOLDER}"
        )
    return cfg
