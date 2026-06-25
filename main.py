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

# ── 2. Robust Detail Scraper ────────────────────────────────────────────────
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

        # A. Attempt to find Booking Date in ALL tables (Robust Strategy)
        # Often data is in <td class="label">Booking Date</td><td>Value</td>
        for td in soup.find_all('td'):
            if "Booking Date" in td.get_text():
                # Find the next sibling <td> which should contain the date
                next_td = td.find_next_sibling('td')
                if next_td:
                    booking_date = next_td.get_text(strip=True)
                    break

        # B. Parse Charges and Agencies using Pandas (Standard Strategy)
        try:
            tables = pd.read_html(io.StringIO(content))
            for df in tables:
                # Search for specific columns
                if 'Offense' in df.columns:
                    charges_str = "; ".join(df['Offense'].astype(str).tolist())
                    if 'Counts' in df.columns:
                        total_counts = df['Counts'].sum()
                if 'Agency' in df.columns:
                    arrest_agencies = "; ".join(df['Agency'].dropna().unique().tolist())
        except:
            pass # Tables might not exist

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

# ── 3. Roster Scraper ──────────────────────────────────────────────────────
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

# ── 4. Main Execution Pipeline ─────────────────────────────────────────────
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_urls = await get_roster_urls(page)
        results = []
        for i, url in enumerate(all_urls):
            data = await get_detail(page, url)
            if data: results.append(data)
            await asyncio.sleep(0.5) 
        await browser.close()

        df = pd.DataFrame(results)
        
        # Dual-save logic
        timestamp = datetime.now().strftime("%Y-%m-%d")
        df.to_csv(f"dane_jail_{timestamp}.csv", index=False)
        df.to_csv("dane_jail_full_scrape.csv", index=False)
        print("Data saved successfully.")

if __name__ == "__main__":
    asyncio.run(main())
