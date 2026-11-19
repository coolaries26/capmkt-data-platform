import pandas as pd

df = pd.read_csv(
    "data/landing/bhavcopy_cm/BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv.zip", dtype=str
)
print(df.columns.tolist())
print(len(df))
print(df.head(3).T)
key = ["TradDt", "TckrSymb", "SctySrs"]  # adjust to the real names
print("duplicate keys:", df.duplicated(key).sum())
print(df["SctySrs"].value_counts().head(10))
print(df.isna().sum()[lambda s: s > 0])
print(df["TradDt"].iloc[0])  # note the date format
