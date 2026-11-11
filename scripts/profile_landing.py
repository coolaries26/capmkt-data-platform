"""Profile landed bhavcopy files before they are loaded. Read-only."""

import io

import pandas as pd

from capmkt_data_platform.ingest.nse_client import read_csv_member
from capmkt_data_platform.settings import get_settings

NUMERIC = [
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "LastPric",
    "PrvsClsgPric",
    "SttlmPric",
    "TtlTradgVol",
    "TtlTrfVal",
    "TtlNbOfTxsExctd",
]
PRICES = ["OpnPric", "HghPric", "LwPric", "ClsPric"]
ISIN_RE = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"

landing = get_settings().landing_dir / "bhavcopy_cm"
for zp in sorted(landing.glob("*.zip")):
    # keep_default_na=False so the series "NA" is not turned into a missing value
    df = pd.read_csv(io.BytesIO(read_csv_member(zp)), dtype=str, keep_default_na=False)
    print(
        f"\n== {zp.name}: {len(df)} rows, {df['TckrSymb'].nunique()} symbols, "
        f"dates={sorted(df['TradDt'].unique())}"
    )

    blank = df[NUMERIC].apply(lambda s: s.str.strip().eq("")).sum()
    print("blank values:", blank[blank > 0].to_dict() or "none")

    num = df[NUMERIC].apply(pd.to_numeric, errors="coerce")
    unparseable = (num.isna() & df[NUMERIC].apply(lambda s: s.str.strip().ne(""))).sum()
    print("non-numeric text:", unparseable[unparseable > 0].to_dict() or "none")

    zero = (num[PRICES] == 0).sum()
    print("zero prices:", zero[zero > 0].to_dict() or "none")
    print("high < low rows:", int((num["HghPric"] < num["LwPric"]).sum()))
    print("bad ISIN format:", int((~df["ISIN"].str.match(ISIN_RE)).sum()))
    print('series "NA" rows:', int((df["SctySrs"] == "NA").sum()))
