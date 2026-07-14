"""
Scrapes the Dane County CJC Jail Snapshot Tableau dashboard for full
resident-level demographic data (race, ethnicity, sex, age, booking date,
length of stay, housing location, etc.) and saves it as a date-stamped CSV.

Usage:
    python scrape_jail_snapshot.py

Output:
    data/jail_snapshot_YYYY-MM-DD.csv

Note on architecture:
    We first load the county's embed page just to discover the underlying
    public.tableau.com URL, then navigate to THAT URL directly as a fresh,
    top-level (first-party) page. This avoids a third-party storage-access
    failure we hit when driving the download from inside the danecounty.gov
    iframe: Chromium denied `requestStorageAccess` for the cross-origin
    Tableau frame, and Tableau's client-side export logic silently failed to
    ever produce a download as a result. Running Tableau as the top-level
    origin removes that restriction entirely.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright

EMBED_URL = "https://cjc.danecounty.gov/Data-and-Dashboards/Jail-Snapshot"
OUTPUT_DIR = "data"
TOTAL_RESIDENTS_CLICK_COORDS = (203, 258)  # position of the "Total Residents" number on the standalone public.tableau.com layout (no county page chrome pushing content down)
MAX_SELECTION_ATTEMPTS = 5
DOWNLOAD_TIMEOUT_MS = 20000


def _attach_debug_listeners(pg, label):
    pg.on(
        "console",
        lambda msg: print(f"[{label} console:{msg.type}] {msg.text}")
        if msg.type == "error"
        else None,
    )
    pg.on("pageerror", lambda err: print(f"[{label} error] {err}"))


async def find_tableau_frame(pg):
    for f in pg.frames:
        if "public.tableau.com" in f.url:
            return f
    return None


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

        # --- Step 1: load the embed page just to discover the real
        # public.tableau.com URL for this specific view ---
        embed_page = await context.new_page()
        _attach_debug_listeners(embed_page, "embed_page")

        await embed_page.goto(EMBED_URL, wait_until="load", timeout=60000)
        await embed_page.wait_for_timeout(5000)

        embed_frame = await find_tableau_frame(embed_page)
        if embed_frame is None:
            await browser.close()
            raise RuntimeError("Could not find the Tableau iframe on the embed page")

        tableau_url = embed_frame.url
        print(f"Discovered Tableau URL: {tableau_url}")
        await embed_page.close()

        # --- Step 2: navigate to that URL directly as a first-party page ---
        page = await context.new_page()
        _attach_debug_listeners(page, "page")

        await page.goto(tableau_url, wait_until="load", timeout=60000)
        await page.wait_for_timeout(5000)
        await page.screenshot(path="debug_direct_tableau_load.png")

        # The direct public.tableau.com page may itself still wrap the viz in
        # an internal iframe, or the viz may now be in the top-level frame.
        # Handle both: prefer a nested tableau frame if present, else use
        # the page itself as the interaction target.
        inner_frame = await find_tableau_frame(page)
        tableau_frame = inner_frame if inner_frame is not None else page.main_frame

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
            await page.screenshot(path="debug_selection_failed.png")
            await browser.close()
            raise RuntimeError(
                "Could not select the Total Residents mark after retries. "
                "Check debug_selection_failed.png - click coordinates may "
                "need recalibrating for the standalone Tableau layout "
                "(toolbar/padding can differ from the embedded iframe)."
            )

        # Open the Download menu, then the "Data" option (opens a new popup page)
        await tableau_frame.get_by_role("button", name="Download").click()
        await page.wait_for_timeout(1000)

        async with context.expect_page(timeout=20000) as new_page_info:
            await tableau_frame.get_by_role("menuitem", name="Data").click()
        data_page = await new_page_info.value
        _attach_debug_listeners(data_page, "data_page")
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

        await data_page.screenshot(path="debug_before_download.png")

        download_locator = data_page.get_by_text("Download", exact=True).first
        await download_locator.wait_for(state="visible", timeout=10000)

        # Log every network request/response/failure on data_page after this
        # point - if Tableau's export needs a server round-trip to generate
        # the file, we should see it fire here even if no download event
        # ever does. This is the piece we lost visibility on last run.
        def log_request(req):
            print(f"[data_page request] {req.method} {req.url}")

        def log_response(res):
            print(f"[data_page response] {res.status} {res.url}")

        def log_request_failed(req):
            print(f"[data_page request FAILED] {req.url} - {req.failure}")

        data_page.on("request", log_request)
        data_page.on("response", log_response)
        data_page.on("requestfailed", log_request_failed)

        download_holder = {}
        download_event = asyncio.Event()

        def handle_download(dl):
            download_holder["download"] = dl
            download_event.set()

        def handle_new_page(new_page):
            new_page.on("download", handle_download)

        context.on("page", handle_new_page)
        data_page.on("download", handle_download)

        # Click the ancestor that's actually the clickable control (button/
        # role=button), not the bare text node.
        clickable = download_locator.locator(
            "xpath=ancestor-or-self::*[self::button or @role='button'][1]"
        )
        target = clickable if await clickable.count() > 0 else download_locator
        await target.click()

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
                "opened after the click, even from the first-party Tableau "
                "URL. Check debug_download_timeout.png and "
                "debug_context_page_*.png for what actually rendered."
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
