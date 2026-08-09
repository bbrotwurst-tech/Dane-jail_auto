"""
Merges the day's Dane County booking/charge data (from the Dane scraper)
with the CJC Jail Snapshot demographic data (race, ethnicity, sex, etc.)
by joining on Namenum, extracted from each resident's detail page URL.

Expects:
    dane_jail_YYYY-MM-DD.csv            (from the Dane scraper, saved at repo root)
    data/jail_snapshot_YYYY-MM-DD.csv   (from the CJC scraper, saved in data/)

Matches files by the DATE IN THE FILENAME, not file modification time.
(An earlier version used os.path.getmtime to find the "most recent" file
of each type, but in GitHub Actions every run starts with a fresh
`actions/checkout`, which resets every file's mtime to checkout time -
so mtime ends up reflecting git's internal checkout order, not which
file was actually scraped most recently. That silently paired mismatched
dates between the two sources.)

If no exact date match exists for today, falls back to the most recent
date that exists in BOTH sources (never mixes across different dates).

Output:
    merged/merged_jail_data_YYYY-MM-DD.csv
"""

import glob
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

MERGED_DIR = "merged"

DANE_PATTERN = "dane_jail_????-??-??.csv"
CJC_PATTERN = os.path.join("data", "jail_snapshot_????-??-??.csv")

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def dated_files(pattern: str) -> dict:
    """Return {date_string: filepath} for every file matching pattern,
    keyed by the date embedded in the filename (not mtime)."""
    result = {}
    for path in glob.glob(pattern):
        m = DATE_RE.search(os.path.basename(path))
        if m:
            result[m.group(1)] = path
    return result


def pick_target_date(dane_dates: dict, cjc_dates: dict, preferred: str) -> str:
    """Pick the date to merge: prefer an exact match on `preferred` if both
    sources have it, else fall back to the most recent date present in
    BOTH sources. Never pairs two different dates together."""
    common_dates = sorted(set(dane_dates) & set(cjc_dates))
    if not common_dates:
        raise FileNotFoundError(
            "No date has files in both dane_jail_*.csv and data/jail_snapshot_*.csv - "
            f"dane dates: {sorted(dane_dates)[-5:]}, cjc dates: {sorted(cjc_dates)[-5:]}"
        )

    if preferred in common_dates:
        return preferred

    fallback = common_dates[-1]
    print(
        f"Warning: no matching pair for {preferred}; falling back to most "
        f"recent common date {fallback}"
    )
    return fallback


def load_dane_data(path: str) -> pd.DataFrame:
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


def load_cjc_data(path: str) -> pd.DataFrame:
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

    dane_dates = dated_files(DANE_PATTERN)
    cjc_dates = dated_files(CJC_PATTERN)

    # Central time, matching the date convention both scrapers use for
    # their own output filenames.
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    target_date = pick_target_date(dane_dates, cjc_dates, preferred=today)

    dane_df = load_dane_data(dane_dates[target_date])
    cjc_df = load_cjc_data(cjc_dates[target_date])

    merged = dane_df.merge(cjc_df, on="Namenum", how="left", suffixes=("_dane", "_cjc"))

    total = len(dane_df)
    matched = merged["Race"].notna().sum() if "Race" in merged.columns else 0
    print(f"Dane rows: {total}")
    print(f"Matched rows: {matched} ({matched / total:.1%})" if total else "No Dane rows")

    output_path = os.path.join(MERGED_DIR, f"merged_jail_data_{target_date}.csv")
    merged.to_csv(output_path, index=False)
    print(f"Saved: {output_path}")

    return output_path


if __name__ == "__main__":
    try:
        merge()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
