## Nov, 08
- **.env** file won't load properly via running `. ./.env` or `source .env` when trying to run `uv run dbt debug --project-dir dbt`
- need to run `set -a; source .env; set +a` before running `uv run dbt debug --project-dir dbt`
## Nov, 09
These are derivatives or reserved fields, so don’t load them: XpryDt, FininstrmActlXpryDt, StrkPric, OptnTp, UndrlygPric, OpnIntrst, ChngInOpnIntrst, NewBrdLotQty, Rsvd1 to Rsvd4. Confirm they’re empty for equity rows before dropping them:
```python
skip = [
    "XpryDt",
    "FininstrmActlXpryDt",
    "StrkPric",
    "OptnTp",
    "UndrlygPric",
    "OpnIntrst",
    "ChngInOpnIntrst",
    "NewBrdLotQty",
    "Rsvd1",
    "Rsvd2",
    "Rsvd3",
    "Rsvd4",
]
print(df[skip].replace("", pd.NA).notna().sum())
```

## Nov, 10
- There is one series with name **NA** which is required to be processed but the same is taken by python as **NULL** so to fix this need to code to skip this by python.
