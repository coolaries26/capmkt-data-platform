"""Parser tests. A small fixture builder produces realistic 34-column bhavcopy files."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date

import pytest

from capmkt_data_platform.ingest.parser import ParseError, parse_bhavcopy

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


def parse(rows: list[dict[str, str]], **kwargs):
    return parse_bhavcopy(
        make_csv(rows, kwargs.pop("header", None)), CFG, kwargs.pop("day", DAY)
    )


def value(parsed, index: int, target: str):
    return parsed.rows[index][parsed.columns.index(target)]


# --- happy path ----------------------------------------------------------------
def test_valid_file_returns_targets_in_yaml_order_and_all_rows():
    parsed = parse([row(), row(TckrSymb="TCS", ISIN="INE467B01029")])
    assert parsed.columns == [m[1] for m in MAPPED]
    assert len(parsed.columns) == 22
    assert parsed.row_count == 2
    assert value(parsed, 1, "symbol") == "TCS"
    assert all(len(r) == 22 for r in parsed.rows)


def test_ignored_columns_are_not_in_output():
    parsed = parse([row()])
    assert not set(IGNORED) & set(parsed.columns)


def test_series_NA_stays_the_text_NA():
    parsed = parse([row(SctySrs="NA", TckrSymb="XYZ"), row(SctySrs="EQ")])
    assert value(parsed, 0, "series") == "NA"


def test_numbers_stay_exact_strings_not_floats():
    parsed = parse([row(ClsPric="104.10", TtlTrfVal="12850000.00")])
    assert value(parsed, 0, "close_price") == "104.10"
    assert value(parsed, 0, "total_traded_value") == "12850000.00"


def test_blank_and_whitespace_values_become_none():
    parsed = parse([row(LastPric="", SttlmPric="   ", Rmks="")])
    assert value(parsed, 0, "last_price") is None
    assert value(parsed, 0, "settlement_price") is None
    assert value(parsed, 0, "remarks") is None


def test_text_values_are_trimmed():
    parsed = parse([row(TckrSymb="  TCS ", ISIN="INE467B01029")])
    assert value(parsed, 0, "symbol") == "TCS"


def test_utf8_bom_in_header_is_tolerated():
    data = b"\xef\xbb\xbf" + make_csv([row()])
    assert parse_bhavcopy(data, CFG, DAY).row_count == 1


def test_same_symbol_in_different_series_is_not_a_duplicate():
    parsed = parse([row(SctySrs="EQ"), row(SctySrs="BE")])
    assert parsed.row_count == 2


# --- header problems -----------------------------------------------------------
def test_missing_mapped_column_is_named_in_the_error():
    header = [c for c in HEADER if c != "ClsPric"]
    with pytest.raises(ParseError, match="ClsPric"):
        parse([row()], header=header)


def test_unknown_extra_column_warns_but_parses(caplog):
    header = [*HEADER, "BrandNewCol"]
    with caplog.at_level(logging.WARNING):
        parsed = parse_bhavcopy(
            make_csv([{**row(), "BrandNewCol": "x"}], header), CFG, DAY
        )
    assert parsed.row_count == 1
    assert "BrandNewCol" in caplog.text


# --- date problems -------------------------------------------------------------
def test_wrong_trade_date_is_rejected():
    with pytest.raises(ParseError, match="2026-11-05"):
        parse([row(TradDt="2026-11-05")])


def test_file_mixing_two_dates_is_rejected():
    with pytest.raises(ParseError, match="expected only"):
        parse([row(), row(TckrSymb="TCS", TradDt="2026-11-05")])


def test_impossible_calendar_date_is_rejected():
    with pytest.raises(ParseError, match="TradDt"):
        parse([row(TradDt="2026-13-45")])


# --- value problems ------------------------------------------------------------
def test_non_numeric_price_is_rejected_and_named():
    with pytest.raises(ParseError, match=r"ClsPric->close_price.*'abc'"):
        parse([row(ClsPric="abc")])


def test_decimal_in_a_bigint_column_is_rejected():
    with pytest.raises(ParseError, match="TtlTradgVol"):
        parse([row(TtlTradgVol="100.0")])


def test_all_problems_are_reported_together():
    with pytest.raises(ParseError) as exc:
        parse([row(ClsPric="abc", TtlTradgVol="1.5")])
    assert "ClsPric" in str(exc.value) and "TtlTradgVol" in str(exc.value)


def test_blank_key_column_is_rejected():
    with pytest.raises(ParseError, match="blank value"):
        parse([row(TckrSymb="")])


def test_duplicate_key_is_rejected():
    with pytest.raises(ParseError, match="duplicate"):
        parse([row(), row()])


# --- unreadable files ----------------------------------------------------------
def test_header_only_file_is_rejected():
    with pytest.raises(ParseError, match="no data rows"):
        parse_bhavcopy((",".join(HEADER) + "\n").encode(), CFG, DAY)


def test_empty_bytes_are_rejected():
    with pytest.raises(ParseError):
        parse_bhavcopy(b"", CFG, DAY)


def test_binary_garbage_is_rejected():
    with pytest.raises(ParseError):
        parse_bhavcopy(b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe", CFG, DAY)


# --- metadata (our bugs raise ValueError, not ParseError) -------------------------
def test_unsupported_type_in_metadata_raises_value_error():
    bad = {
        **CFG,
        "columns": [{"source": "TradDt", "target": "trade_date", "type": "uuid"}],
    }
    with pytest.raises(ValueError, match="uuid"):
        parse_bhavcopy(make_csv([row()]), bad, DAY)


def test_metadata_without_trade_date_raises_value_error():
    bad = {**CFG, "columns": [c for c in CFG["columns"] if c["target"] != "trade_date"]}
    with pytest.raises(ValueError, match="trade_date"):
        parse_bhavcopy(make_csv([row()]), bad, DAY)
