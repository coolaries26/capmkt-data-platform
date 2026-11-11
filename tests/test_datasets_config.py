from pathlib import Path

import yaml

from capmkt_data_platform.settings import PROJECT_ROOT

HEADER = [
    "TradDt",
    "BizDt",
    "Sgmt",
    "Src",
    "FinInstrmTp",
    "FinInstrmId",
    "ISIN",
    "TckrSymb",
    "SctySrs",
    "XpryDt",
    "FininstrmActlXpryDt",
    "StrkPric",
    "OptnTp",
    "FinInstrmNm",
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "LastPric",
    "PrvsClsgPric",
    "UndrlygPric",
    "SttlmPric",
    "OpnIntrst",
    "ChngInOpnIntrst",
    "TtlTradgVol",
    "TtlTrfVal",
    "TtlNbOfTxsExctd",
    "SsnId",
    "NewBrdLotQty",
    "Rmks",
    "Rsvd1",
    "Rsvd2",
    "Rsvd3",
    "Rsvd4",
]


def load_cfg() -> dict:
    path = Path(PROJECT_ROOT) / "config" / "datasets.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["datasets"]["bhavcopy_cm"]


def test_every_header_column_is_mapped_or_ignored():
    cfg = load_cfg()
    mapped = [c["source"] for c in cfg["columns"]]
    ignored = cfg["ignored_columns"]
    assert not set(mapped) & set(ignored), "a column is both mapped and ignored"
    assert set(mapped) | set(ignored) == set(HEADER)


def test_mapped_targets_are_unique():
    targets = [c["target"] for c in load_cfg()["columns"]]
    assert len(targets) == len(set(targets))
