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

        # --- Step 1: click the top "Download" control ---
        # On Tableau's Full Data export view, this first click typically opens
        # a modal/dialog with format options rather than firing the download
        # itself. We screenshot right after to confirm what actually rendered.
        await data_page.screenshot(path="debug_before_download.png")
        await data_page.click("text=Download")
        await data_page.wait_for_timeout(1000)
        await data_page.screenshot(path="debug_after_download_click.png")

        # --- Step 2: find and click the real confirm/export control ---
        # Try a few likely selectors for the modal's actual export button,
        # in order, and use whichever one is present. Adjust/add to this
        # list once debug_after_download_click.png shows the real label.
        confirm_selectors = [
            "button:has-text('Download')",
            "button:has-text('Export')",
            "text=Download Full Data",
            "[role='button']:has-text('Download')",
        ]

        confirm_locator = None
        for sel in confirm_selectors:
            loc = data_page.locator(sel)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    confirm_locator = loc.first
                    break
            except Exception:
                continue

        if confirm_locator is None:
            await data_page.screenshot(path="debug_no_confirm_button_found.png")
            await browser.close()
            raise RuntimeError(
                "Could not find a confirm/export button in the download modal. "
                "Check debug_after_download_click.png to identify the correct selector."
            )

        async with data_page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
            await confirm_locator.click()
        download = await download_info.value

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
