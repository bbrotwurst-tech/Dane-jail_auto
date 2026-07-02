import io
import asyncio
import pandas as pd
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime

# Import the classification engine from your constants file
from constants import WI_CHARGE_MAP

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

    if 'Felony' in levels: return 'Felony'
    if 'Misdemeanor' in levels: return 'Misdemeanor'
    if 'Civil' in levels: return 'Civil'
    return 'Unknown'


# ── 2. SCRAPING LOGIC ────────────────────────────────────────────────
async def get_detail(page, url):
    try:
        await page.goto(url, wait_until='networkidle', timeout=30000)
        content = await page.content()
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

            # Initialize accumulation lists and variables to prevent overwrite
            all_names = []
            all_codes = []
            accumulated_counts = 0
            all_agencies = set()

            for df in tables:
                if 'Offense' in df.columns:
                    # Append all offenses found across all tables
                    for o in df['Offense'].tolist():
                        name, code = split_charge_and_statute(str(o))
                        all_names.append(name)
                        all_codes.append(code if code else "")

                    if 'Counts' in df.columns:
                        accumulated_counts += df['Counts'].sum()

                if 'Agency' in df.columns:
                    # Collect all distinct agencies across tables
                    all_agencies.update(df['Agency'].dropna().unique().tolist())

            # Combine accumulated records into final strings
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

async def get_roster_urls(page):
    await page.goto("https://www.danesheriff.com/Residents", wait_until='networkidle')
    base_url = "https://www.danesheriff.com"
    all_urls = set()
    while True:
        content = await page.content()
        soup = BeautifulSoup(content, 'lxml')
        for a in soup.find_all('a', href=True):
            if '/Residents/Detail/' in a['href']:
                all_urls.add(base_url + a['href'])
        next_li = page.locator("#tblInmates_next")
        class_list = await next_li.get_attribute("class")
        if class_list and "disabled" in class_list:
            break
        await page.locator("#tblInmates_next a").click()
        await page.wait_for_load_state("networkidle")
    return list(all_urls)

async def scrape_all_data():
    print("Initializing browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Fetching roster URLs...")
        all_urls = await get_roster_urls(page)
        print(f"Found {len(all_urls)} inmates. Scraping details...")

        results = []
        for i, url in enumerate(all_urls):
            data = await get_detail(page, url)
            if data:
                results.append(data)

            if (i + 1) % 50 == 0:
                print(f"  Scraped {i + 1} of {len(all_urls)}...")

            await asyncio.sleep(0.5)

        await browser.close()
        return pd.DataFrame(results)


# ── 3. PIPELINE ORCHESTRATOR ─────────────────────────────────────────
def run_scraper():
    """Synchronous wrapper to run the async Playwright scraper"""
    return asyncio.run(scrape_all_data())

def main():
    print("Starting pipeline...")

    df = run_scraper()
    if df.empty:
        print("No data retrieved.")
        return

    print(f"Classifying {len(df)} records using the charge map...")
    df['charge_level'] = df['charges_str'].apply(classify_charge_list)

    timestamp = datetime.now().strftime("%Y-%m-%d")
    daily_filename = f"dane_jail_{timestamp}.csv"
    full_filename = "dane_jail_full_scrape.csv"

    df.to_csv(daily_filename, index=False)
    df.to_csv(full_filename, index=False)

    print(f"Pipeline complete! Saved data to {daily_filename} and {full_filename}")

if __name__ == "__main__":
    main()

