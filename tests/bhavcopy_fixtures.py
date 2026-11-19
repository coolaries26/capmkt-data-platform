"""Shared fixtures for parser and loader tests: realistic 34-column bhavcopy files.

Plain helpers (no pytest fixtures), importable from any test module in tests/.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

DAY = date(2026, 11, 6)

# (source column, target column, type): the 22 mapped columns
MAPPED = [
    ("TradDt", "trade_date", "date"),
    ("BizDt", "business_date", "date"),
    ("Sgmt", "segment", "text"),
    ("Src", "source", "text"),
    ("FinInstrmTp", "instrument_type", "text"),
    ("FinInstrmId", "instrument_id", "text"),
    ("ISIN", "isin", "text"),
    ("TckrSymb", "symbol", "text"),
    ("SctySrs", "series", "text"),
    ("FinInstrmNm", "instrument_name", "text"),
    ("OpnPric", "open_price", "numeric"),
    ("HghPric", "high_price", "numeric"),
    ("LwPric", "low_price", "numeric"),
    ("ClsPric", "close_price", "numeric"),
    ("LastPric", "last_price", "numeric"),
    ("PrvsClsgPric", "prev_close_price", "numeric"),
    ("SttlmPric", "settlement_price", "numeric"),
    ("TtlTradgVol", "total_traded_qty", "bigint"),
    ("TtlTrfVal", "total_traded_value", "numeric"),
    ("TtlNbOfTxsExctd", "total_trades", "bigint"),
    ("SsnId", "session_id", "text"),
    ("Rmks", "remarks", "text"),
]
IGNORED = [
    "XpryDt", "FininstrmActlXpryDt", "StrkPric", "OptnTp", "UndrlygPric", "OpnIntrst",
    "ChngInOpnIntrst", "NewBrdLotQty", "Rsvd1", "Rsvd2", "Rsvd3", "Rsvd4",
]  # fmt: skip
HEADER = [
    m[0] for m in MAPPED
] + IGNORED  # 34 columns (order does not matter to the parser)

CFG = {
    "columns": [{"source": s, "target": t, "type": ty} for s, t, ty in MAPPED],
    "ignored_columns": IGNORED,
    "natural_key": ["trade_date", "symbol", "series"],
    "target_table": "raw.bhavcopy_cm",
}

DEFAULTS = {
    "TradDt": "2026-11-06", "BizDt": "2026-11-06", "Sgmt": "CM", "Src": "NSE",
    "FinInstrmTp": "STK", "FinInstrmId": "2885", "ISIN": "INE002A01018",
    "TckrSymb": "RELIANCE", "SctySrs": "EQ", "FinInstrmNm": "RELIANCE INDUSTRIES LTD",
    "OpnPric": "100.50", "HghPric": "105.00", "LwPric": "99.25", "ClsPric": "104.10",
    "LastPric": "104.00", "PrvsClsgPric": "100.00", "SttlmPric": "104.10",
    "TtlTradgVol": "123456", "TtlTrfVal": "12850000.00", "TtlNbOfTxsExctd": "4567",
    "SsnId": "F1",
}  # fmt: skip


def row(**overrides: str) -> dict[str, str]:
    return {**{c: "" for c in HEADER}, **DEFAULTS, **overrides}


def make_csv(rows: list[dict[str, str]], header: list[str] | None = None) -> bytes:
    header = header or HEADER
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=header, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def make_zip(csv_bytes: bytes, name: str = "BhavCopy.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_bytes)
    return buf.getvalue()
