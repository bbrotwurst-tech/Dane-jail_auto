"""
Dane County Sheriff's Office inmate roster scraper - plain requests version.

Playwright was originally used for this entire pipeline (roster pagination
+ detail pages), but testing showed neither actually needs a browser:
  - The roster page (/Residents) embeds ALL inmate detail links in the
    initial HTML response - DataTables here does client-side-only
    pagination (a display trick), not AJAX-loaded pages. A single plain
    GET request returns the full roster.
  - Detail pages are fully server-rendered HTML with no JS required to
    show booking date, status, or offense tables.

This version replaces Playwright entirely with `requests` + a thread pool
for concurrent detail-page fetches, which should be dramatically faster
and has far fewer moving parts to break (no browser binary, no timing
races, no JS-rendering dependency).

Usage:
    python scrape_dane_roster.py

Output:
    dane_jail_<YYYY-MM-DD>.csv
    dane_jail_full_scrape.csv
"""

import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Import the classification engine from your constants file
from constants import WI_CHARGE_MAP

BASE_URL = "https://www.danesheriff.com"
ROSTER_URL = f"{BASE_URL}/Residents"
MAX_WORKERS = 10  # concurrent detail-page requests - polite but fast
REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )
}

# ── Helpers: split charge text from statute citation ──────────────────
STATUTE_RE = re.compile(r'\s+(\d+\.\d+[A-Za-z]?(?:\([^)]*\))*[A-Za-z0-9]*)\s*$')
COUNT_SUFFIX_RE = re.compile(r'\s*\(\d+\s*CT\)\s*$')


def split_charge_and_statute(charge):
    """
    Splits a raw offense string into (charge_name, statute_code).
    Strips count suffixes like '(1 CT)' and pulls off a trailing
    Wisconsin statute citation, e.g. '939.32', '973.055(1)',
    '346.65(2)(G)2', '961.49(1M)(B)1'.
    Returns (charge_name, statute_code_or_None).
    """
    charge = charge.strip().upper()
    charge = COUNT_SUFFIX_RE.sub('', charge).strip()

    statute_match = STATUTE_RE.search(charge)
    statute_code = None
    if statute_match:
        statute_code = statute_match.group(1)
        charge = STATUTE_RE.sub('', charge).strip()

    return charge, statute_code


def clean_charge_text(charge):
    """Backwards-compatible helper: just returns the cleaned charge name."""
    name, _ = split_charge_and_statute(charge)
    return name


# ── 1. TRANSFORMATION LOGIC (Powered by constants.py) ───────────────
def classify_charge_list(charges_str):
    """
    Parses charge string and determines severity level based on WI_CHARGE_MAP.
    """
    if pd.isna(charges_str) or str(charges_str).strip() == '':
        return 'None'

    charges = [c.strip() for c in str(charges_str).split(';') if c.strip() != '']

    levels = set()
    for charge in charges:
        charge_clean = clean_charge_text(charge)

        if charge_clean in WI_CHARGE_MAP:
            levels.add(WI_CHARGE_MAP[charge_clean])
        else:
            print(f"  [DEBUG] Unmapped Charge Found: '{charge_clean}'")
            levels.add('Unknown')

    if 'Felony' in levels:
        return 'Felony'
    if 'Misdemeanor' in levels:
        return 'Misdemeanor'
    if 'Civil' in levels:
        return 'Civil'
    return 'Unknown'


# ── 2. SCRAPING LOGIC ────────────────────────────────────────────────
def get_roster_urls(session):
    """
    Fetch the roster page once and pull every inmate detail link out of
    the raw HTML. DataTables embeds the full dataset up front here, so no
    pagination/clicking is needed - confirmed via direct testing (768
    unique links returned from a single plain GET, matching the full
    roster count).
    """
    resp = session.get(ROSTER_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    links = set(re.findall(r'/Residents/Detail/\d+', resp.text))
    return [BASE_URL + link for link in links]


def get_detail(session, url):
    try:
        resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

        if not resp.ok:
            print(f"  [SKIP] {url} returned status {resp.status_code}")
            return None

        content = resp.text
        soup = BeautifulSoup(content, 'lxml')

        booking_date = None
        judicial_status = None
        charges_str = ""
        statute_codes_str = ""
        total_counts = 0
        arrest_agencies = "Unknown"

        # Find Booking Date and Status (exact label match to avoid
        # accidentally matching unrelated cells that merely contain
        # the word "status" or "date" somewhere in their text)
        for td in soup.find_all('td'):
            label = td.get_text(strip=True)

            if label == "Booking Date" and booking_date is None:
                next_td = td.find_next_sibling('td')
                if next_td:
                    booking_date = next_td.get_text(strip=True)

            elif label == "Status" and judicial_status is None:
                next_td = td.find_next_sibling('td')
                if next_td:
                    judicial_status = next_td.get_text(strip=True)

            if booking_date is not None and judicial_status is not None:
                break

        # Parse Charges and Agencies using Pandas
        try:
            tables = pd.read_html(io.StringIO(content))

            all_names = []
            all_codes = []
            accumulated_counts = 0
            all_agencies = set()

            for df in tables:
                if 'Offense' in df.columns:
                    for o in df['Offense'].tolist():
                        name, code = split_charge_and_statute(str(o))
                        all_names.append(name)
                        all_codes.append(code if code else "")

                    if 'Counts' in df.columns:
                        accumulated_counts += df['Counts'].sum()

                if 'Agency' in df.columns:
                    all_agencies.update(df['Agency'].dropna().unique().tolist())

            charges_str = "; ".join(all_names)
            statute_codes_str = "; ".join(all_codes)
            total_counts = accumulated_counts
            if all_agencies:
                arrest_agencies = "; ".join(list(all_agencies))

        except Exception:
            pass  # Tables might not exist

        return {
            'url': url,
            'charges_str': charges_str,
            'statute_codes': statute_codes_str,
            'total_charge_counts': total_counts,
            'arrest_agencies': arrest_agencies,
            'booking_date': booking_date,
            'judicial_status': judicial_status,
        }
    except Exception as e:
        print(f"Error on {url}: {e}")
        return None


def scrape_all_data():
    session = requests.Session()

    print("Fetching roster URLs...")
    all_urls = get_roster_urls(session)
    print(f"Found {len(all_urls)} inmates. Scraping details (concurrent, {MAX_WORKERS} workers)...")

    results = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_detail, session, url): url for url in all_urls}

        completed = 0
        for future in as_completed(futures):
            data = future.result()
            if data:
                results.append(data)
            completed += 1
            if completed % 50 == 0:
                print(f"  Scraped {completed} of {len(all_urls)}...")

    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s")

    return pd.DataFrame(results)


# ── 3. PIPELINE ORCHESTRATOR ─────────────────────────────────────────
def main():
    print("Starting pipeline...")

    df = scrape_all_data()
    if df.empty:
        print("No data retrieved.")
        return

    print(f"Classifying {len(df)} records using the charge map...")
    df['charge_level'] = df['charges_str'].apply(classify_charge_list)

    # Use Central time explicitly so the date label matches Madison's
    # local calendar day, regardless of what timezone the machine
    # running this script (e.g. a GitHub Actions runner in UTC) is in.
    timestamp = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    daily_filename = f"dane_jail_{timestamp}.csv"
    full_filename = "dane_jail_full_scrape.csv"

    df.to_csv(daily_filename, index=False)
    df.to_csv(full_filename, index=False)

    print(f"Pipeline complete! Saved data to {daily_filename} and {full_filename}")


if __name__ == "__main__":
    main()
