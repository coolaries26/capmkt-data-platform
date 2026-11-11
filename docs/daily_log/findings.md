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

## Nov, 11
1. When does NSE publish? At 14:28 IST the day’s file wasn’t up, which fits the “evening” assumption. Record the real time. Run this command around 17:00, 18:00 and 19:00 tonight, and note when the first DOWNLOADED appears:

```bash
uv run python -m capmkt_data_platform.cli download --date 2026-11-11
```
This decides the DAG’s schedule time on Day 12. If it’s out by 18:00, the 19:30 schedule has plenty of margin. If it’s later, move the schedule or lengthen the retries.

2. Why was 10 Nov a 404? **Nov 10 is exchange holiday** A Tuesday with no file points to an exchange holiday, probably around Diwali, but I haven’t verified that. Check the NSE holiday list. Whatever you find is your first real calendar data point.

This also exposes a gap in the design. backfill skips weekends, but exchanges sometimes hold special sessions on a Saturday or Sunday, for example Muhurat trading around Diwali. 8 Nov was a Sunday this year. To test whether a file exists for it, run one command (download doesn’t skip weekends):

```bash
uv run python -m capmkt_data_platform.cli download --date 2026-11-08
```
It returned a file, as there was a special session on that day, it confirms the weekday filter can miss real data. Therefore the Week 2 trading calendar should list special sessions as well as holidays, and the backfill should follow the calendar instead of assuming Monday to Friday.

## Findings
- Publish time: missing at 14:28 IST, present by 17:04.
- 10 Nov: a holiday (404).
- 8 Nov (Sunday): a file exists, so special sessions are real. Write down the file’s row count and compare it with a normal day. A Muhurat session should look smaller in traded value. Run the profiler again after downloading it.
- The NA series and blank/zero/ISIN findings. by `scripts/profile_landing.py`
