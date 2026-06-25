import io
import asyncio
import pandas as pd
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime

# Import the classification engine from your new file!
from constants import WI_CHARGE_MAP

# ── 1. TRANSFORMATION LOGIC (Powered by constants.py) ───────────────
def classify_charge_list(charges_str):
    """
    Parses charge string and determines severity level based on WI_CHARGE_MAP.
    """
    if pd.isna(charges_str) or str(charges_str).strip() == '':
        return 'None'
    
    # Split by semicolon and clean whitespace
    charges = [c.strip().upper() for c in str(charges_str).split(';') if c.strip() != '']
    
    levels = set()
    for charge in charges:
        # Regex to strip counts like "(1 CT)" to match keys in constants.py
        charge_clean = re.sub(r'\s*\(\d+\s*CT\)\s*$', '', charge).strip()
        
        # Check map
        if charge_clean in WI_CHARGE_MAP:
            levels.add(WI_CHARGE_MAP[charge_clean])
        else:
            # Helpful logging to identify new charges for your constants.py
            print(f"  [DEBUG] Unmapped Charge Found: '{charge_clean}'")
            levels.add('Unknown')
            
    # Hierarchy Logic (Felony overrides Misdemeanor, etc.)
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
        
        # Initialize defaults
        booking_date = None
        charges_str = ""
        total_counts = 0
        arrest_agencies = "Unknown"

        # Find Booking Date
        for td in soup.find_all('td'):
            if "Booking Date" in td.get_text():
                next_td = td.find_next_sibling('td')
                if next_td:
                    booking_date = next_td.get_text(strip=True)
                    break

        # Parse Charges and Agencies using Pandas
        try:
            tables = pd.read_html(io.StringIO(content))
            for df in tables:
                if 'Offense' in df.columns:
                    charges_str = "; ".join(df['Offense'].astype(str).tolist())
                    if 'Counts' in df.columns:
                        total_counts = df['Counts'].sum()
                if 'Agency' in df.columns:
                    arrest_agencies = "; ".join(df['Agency'].dropna().unique().tolist())
        except Exception:
            pass # Tables might not exist

        return {
            'url': url,
            'charges_str': charges_str,
            'total_charge_counts': total_counts,
            'arrest_agencies': arrest_agencies,
            'booking_date': booking_date
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
            
            # Progress tracker in the terminal so you know it isn't frozen
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
    
    # 1. Fetch Data
    df = run_scraper()
    if df.empty:
        print("No data retrieved.")
        return
    
    # 2. Transform: Apply classification
    print(f"Classifying {len(df)} records using the charge map...")
    df['charge_level'] = df['charges_str'].apply(classify_charge_list)
    
    # 3. Save: Output the clean data
    timestamp = datetime.now().strftime("%Y-%m-%d")
    daily_filename = f"dane_jail_{timestamp}.csv"
    full_filename = "dane_jail_full_scrape.csv"
    
    df.to_csv(daily_filename, index=False)
    df.to_csv(full_filename, index=False)
    
    print(f"Pipeline complete! Saved data to {daily_filename} and {full_filename}")

if __name__ == "__main__":
    main()
