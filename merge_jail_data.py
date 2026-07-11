"""
Merges the day's Dane County booking/charge data (from the Dane scraper)
with the CJC Jail Snapshot demographic data (race, ethnicity, sex, etc.)
by joining on Namenum, extracted from each resident's detail page URL.

Expects:
    data/dane_jail_YYYY-MM-DD.csv       (from the Dane scraper)
    data/jail_snapshot_YYYY-MM-DD.csv   (from the CJC scraper)

Falls back to the most recent available file of each type if today's
exact date isn't found (in case scraper timing drifts across midnight).

Output:
    data/merged/merged_jail_data_YYYY-MM-DD.csv
"""

import glob
import os
import re
import sys
from datetime import datetime, timezone

import pandas as pd

DATA_DIR = "data"
MERGED_DIR = os.path.join(DATA_DIR, "merged")

DANE_PATTERN = os.path.join(DATA_DIR, "dane_jail_*.csv")
CJC_PATTERN = os.path.join(DATA_DIR, "jail_snapshot_*.csv")


def most_recent_file(pattern: str) -> str:
    """Return the most recently modified file matching the glob pattern."""
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"No files found matching {pattern}")
    return max(matches, key=os.path.getmtime)


def load_dane_data() -> pd.DataFrame:
    path = most_recent_file(DANE_PATTERN)
    print(f"Loading Dane data from: {path}")
    df = pd.read_csv(path)

    if "url" not in df.columns:
        raise KeyError(
            f"Expected a 'url' column in {path} to extract Namenum, "
            f"but found columns: {df.columns.tolist()}"
        )

    df["Namenum"] = df["url"].str.extract(r"/Detail/(\d+)")
    missing = df["Namenum"].isna().sum()
    if missing:
        print(f"Warning: {missing} rows had no Namenum extractable from url")
    df["Namenum"] = pd.to_numeric(df["Namenum"], errors="coerce").astype("Int64")

    return df


def load_cjc_data() -> pd.DataFrame:
    path = most_recent_file(CJC_PATTERN)
    print(f"Loading CJC data from: {path}")
    df = pd.read_csv(path)

    if "Namenum" not in df.columns:
        raise KeyError(
            f"Expected a 'Namenum' column in {path}, "
            f"but found columns: {df.columns.tolist()}"
        )
    df["Namenum"] = pd.to_numeric(df["Namenum"], errors="coerce").astype("Int64")

    return df


def merge():
    os.makedirs(MERGED_DIR, exist_ok=True)

    dane_df = load_dane_data()
    cjc_df = load_cjc_data()

    merged = dane_df.merge(cjc_df, on="Namenum", how="left", suffixes=("_dane", "_cjc"))

    total = len(dane_df)
    matched = merged["Race"].notna().sum() if "Race" in merged.columns else 0
    print(f"Dane rows: {total}")
    print(f"Matched rows: {matched} ({matched / total:.1%})" if total else "No Dane rows")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = os.path.join(MERGED_DIR, f"merged_jail_data_{today}.csv")
    merged.to_csv(output_path, index=False)
    print(f"Saved: {output_path}")

    return output_path


if __name__ == "__main__":
    try:
        merge()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)

