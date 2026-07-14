"""
Scrapes the Dane County CJC Jail Snapshot Tableau dashboard for full
resident-level demographic data (race, ethnicity, sex, age, booking date,
length of stay, housing location, etc.) and saves it as a date-stamped CSV.

Usage:
    python scrape_jail_snapshot.py

Output:
    data/jail_snapshot_YYYY-MM-DD.csv
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright

URL = "https://cjc.danecounty.gov/Data-and-Dashboards/Jail-Snapshot"
OUTPUT_DIR = "data"
TOTAL_RESIDENTS_CLICK_COORDS = (306, 597)  # position of the "Total Residents" number
MAX_SELECTION_ATTEMPTS = 5
DOWNLOAD_TIMEOUT_MS = 20000


async def scrape():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"jail_snapshot_{today}.csv")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 1550},
            accept_downloads=True,
        )
        page = await context.new_page()

        await page.goto(URL, wait_until="load", timeout=60000)
        await page.wait_for_timeout(5000)

        tableau_frame = None
        for f in page.frames:
            if "public.tableau.com" in f.url:
                tableau_frame = f
                break

        if tableau_frame is None:
            await browser.close()
            raise RuntimeError("Could not find the Tableau iframe on the page")

        # Select the "Total Residents" mark - retry since selection is flaky
        selected = False
        for attempt in range(MAX_SELECTION_ATTEMPTS):
            await page.mouse.click(*TOTAL_RESIDENTS_CLICK_COORDS)
            await page.wait_for_timeout(1500)
            snapshot = await tableau_frame.locator("body").aria_snapshot()
            if "Mark selected" in snapshot:
                selected = True
                break

        if not selected:
            await browser.close()
            raise RuntimeError("Could not select the Total Residents mark after retries")

        # Open the Download menu, then the "Data" option (opens a new popup page)
        await tableau_frame.get_by_role("button", name="Download").click()
        await page.wait_for_timeout(1000)

        async with context.expect_page(timeout=20000) as new_page_info:
            await tableau_frame.get_by_role("menuitem", name="Data").click()
        data_page = await new_page_info.value
        await data_page.wait_for_timeout(2000)
        await data_page.screenshot(path="debug_popup_opened.png")

        # Switch to Full Data tab and select all fields
        await data_page.click("text=Full Data")
        await data_page.wait_for_timeout(1500)
        await data_page.click("text=Show Fields")
        await data_page.wait_for_timeout(1000)
        await data_page.click("text=(All)")
        await data_page.wait_for_timeout(1000)
        await data_page.keyboard.press("Escape")
        await data_page.wait_for_timeout(500)

        # The "See the Tableau browser window for download information"
        # banner indicates the actual download may fire in a NEW tab/window
        # opened after this click, not on data_page itself. So we listen for
        # a "download" event on any page in the context - whichever page it
        # actually fires on - rather than scoping expect_download to
        # data_page alone.
        await data_page.screenshot(path="debug_before_download.png")

        download_locator = data_page.get_by_text("Download", exact=True).first
        await download_locator.wait_for(state="visible", timeout=10000)

        download_holder = {}
        download_event = asyncio.Event()

        def handle_download(dl):
            download_holder["download"] = dl
            download_event.set()

        def handle_new_page(new_page):
            new_page.on("download", handle_download)

        context.on("page", handle_new_page)
        data_page.on("download", handle_download)

        await download_locator.click()

        try:
            await asyncio.wait_for(
                download_event.wait(), timeout=DOWNLOAD_TIMEOUT_MS / 1000
            )
        except asyncio.TimeoutError:
            await data_page.screenshot(path="debug_download_timeout.png")
            for i, p in enumerate(context.pages):
                try:
                    await p.screenshot(path=f"debug_context_page_{i}.png")
                except Exception:
                    pass
            await browser.close()
            raise RuntimeError(
                "No 'download' event fired on data_page or any new page "
                "opened after the click. Check debug_download_timeout.png "
                "and debug_context_page_*.png for what actually rendered."
            )

        download = download_holder["download"]

        await download.save_as(output_path)
        print(f"Saved: {output_path}")

        await browser.close()
        return output_path


if __name__ == "__main__":
    try:
        path = asyncio.run(scrape())
        print(f"Success: {path}")
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
