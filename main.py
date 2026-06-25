import io
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime

# ── 1. Smart Classification Logic ──────────────────────────────────────────
def classify(charges_str):
    if not charges_str or charges_str.strip() == '': return 'None'
    c = charges_str.upper()

    # Priority: Civil/Hold > Felony > Misdemeanor
    if any(k in c for k in ['PROBATION', 'PAROLE', 'HOLD', 'WRIT', 'EXTRADITION', 'SENTENCED', 'PRETRIAL']):
        return 'Civil'
    if any(k in c for k in ['HOMICIDE', 'SEXUAL ASSAULT', 'ROBBERY', 'METHAMPHETAMINE', 'COCAINE',
                            'FIREARM', 'FELON', 'BURGLARY', 'STALKING', 'STRANGULATION',
                            'TRAFFICKING', 'BAIL JUMPING - FELONY', 'BATTERY TO AN ELDER']):
        return 'Felony'
    if any(k in c for k in ['BATTERY', 'DISORDERLY CONDUCT', 'THEFT', 'OWI', 'OPERATING WHILE',
                            'RESISTING', 'DRUG PARAPHERNALIA', 'BAIL JUMPING', 'MUNICIPAL']):
        return 'Misdemeanor'
    return 'Unknown'

# ── 2. Detail Scraper ───────────────────────────────────────────────────────
async def get_detail(page, url):
    try:
        await page.goto(url, wait_until='networkidle', timeout=30000)
        content = await page.content()
        tables = pd.read_html(io.StringIO(content))

        charges_str = ""
        total_counts = 0
        arrest_agencies = "Unknown"

        if len(tables) > 2:
            charges_df = tables[2]
            if 'Offense' in charges_df.columns:
                offense_list = charges_df['Offense'].astype(str).tolist()
                charges_str = "; ".join(offense_list)
                if 'Counts' in charges_df.columns:
                    total_counts = charges_df['Counts'].sum()

        if len(tables) > 1:
            agency_df = tables[1]
            if 'Agency' in agency_df.columns:
                arrest_agencies = "; ".join(agency_df['Agency'].dropna().unique().tolist())

        soup = BeautifulSoup(content, 'lxml')
        booking_date = None
        date_label = soup.find(string=lambda t: t and "Booking Date" in t)
        if date_label:
            booking_date = date_label.find_parent().get_text(separator=' ').replace('Booking Date', '').strip()

        return {
            'url': url,
            'charges_str': charges_str,
            'charge_level': classify(charges_str),
            'total_charge_counts': total_counts,
            'arrest_agencies': arrest_agencies,
            'booking_date': booking_date
        }
    except Exception as e:
        print(f"Error on {url}: {e}")
        return None

# ── 3. Roster Scraper (with Pagination) ───────────────────────────────────
async def get_roster_urls(page):
    await page.goto("https://www.danesheriff.com/Residents", wait_until='networkidle')
    base_url = "https://www.danesheriff.com"
    all_urls = set()

    while True:
        content = await page.content()
        soup = BeautifulSoup(content, 'lxml')
        
        # Extract links on current page
        for a in soup.find_all('a', href=True):
            if '/Residents/Detail/' in a['href']:
                all_urls.add(base_url + a['href'])
        
        print(f"Current count: {len(all_urls)} unique inmates found...")

        # Look for "Next" button
        next_button = page.locator("text=Next") 
        
        # If button exists and is clickable, move to next page
        if await next_button.count() > 0 and await next_button.is_visible():
            await next_button.click()
            await page.wait_for_load_state("networkidle")
        else:
            print("No more pages found.")
            break
            
    return list(all_urls)

# ── 4. Main Execution Pipeline ────────────────────────────────────────────
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Fetching roster list (this may take a moment)...")
        all_urls = await get_roster_urls(page)
        print(f"Total inmates found: {len(all_urls)}. Starting detail scrape...")

        results = []
        for i, url in enumerate(all_urls):
            # Print progress every 5 entries
            if (i+1) % 5 == 0:
                print(f"[{i+1}/{len(all_urls)}] scraping...")
                
            data = await get_detail(page, url)
            if data:
                results.append(data)
            await asyncio.sleep(0.5) 

        await browser.close()

        df = pd.DataFrame(results)
        df.to_csv("dane_jail_full_scrape.csv", index=False)
        print("Done! Data saved to dane_jail_full_scrape.csv")

if __name__ == "__main__":
    asyncio.run(main())



