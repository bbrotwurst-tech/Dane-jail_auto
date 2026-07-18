"""
Scrapes the Dane County CJC Jail Snapshot Tableau dashboard for full
resident-level demographic data (race, ethnicity, sex, age, booking date,
length of stay, housing location, etc.) and saves it as a date-stamped CSV.

Usage:
    python cjc_jail_snapshot_scraper.py

Output:
    data/jail_snapshot_YYYY-MM-DD.csv

Architecture note (why this approach):
    Two other approaches were tried and ruled out first:
      1. Driving Tableau's "Download" button via Playwright - the click
         lands correctly (confirmed via a document-level click listener,
         real trusted event, correct button element) but produces zero
         downstream effect: no network request, no console error, no new
         page, no download event. Root cause was never conclusively
         identified even after ruling out third-party storage-access
         issues, File System Access API headless limitations, and
         readiness/timing races.
      2. Hitting Tableau's internal VizQL bootstrapSession API directly
         (via the `tableauscraper` library) - blocked by AWS WAF bot
         protection, which serves a JS CAPTCHA challenge page to any
         client without a real browser engine (confirmed: the raw response
         was the AwsWAFScript challenge page, not data).

    This version sidesteps both problems: instead of triggering a file
    download, it reads the Full Data table directly out of the rendered
    DOM using a real Playwright-driven browser (so it passes the WAF
    challenge just like a normal user would). It drives the grid's custom
    virtualization with real mouse wheel events, doing a full horizontal
    sweep at EVERY vertical scroll step (not just a handful of sampled
    offsets) using aria-rowindex/aria-colindex as stable anchors to merge
    everything into one row/column matrix. An earlier version swept
    horizontally only at 4 sampled vertical positions, which produced the
    right row COUNT (731, matching the dashboard's own total) but left
    most rows with only their first ~10 of 28 columns ever captured -
    those rows just weren't visible during one of the sparse sample
    points. This version is slower (a full sweep per vertical step) but
    actually complete.

    Header-prefix note: header cells sometimes come back with the
    worksheet name ("snapshot") concatenated directly onto the real field
    name with no separator (e.g. "snapshotNamenum" instead of "Namenum").
    Which variant gets captured depends on which render pass first
    populated that header cell, so it's stripped defensively below rather
    than relying on catching a "clean" pass.
"""

import asyncio
import csv
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

EMBED_URL = "https://cjc.danecounty.gov/Data-and-Dashboards/Jail-Snapshot"
OUTPUT_DIR = "data"
TOTAL_RESIDENTS_CLICK_COORDS = (203, 258)  # position of the "Total Residents" number on the standalone public.tableau.com layout
MAX_SELECTION_ATTEMPTS = 5
ROW_COUNT_OVERRIDE = "2000"  # comfortably above the ~734 total residents, so everything loads in one page
EXPECTED_KEY_COLUMN = "Namenum"  # sanity check: this must survive prefix-stripping


def _attach_debug_listeners(pg, label):
    pg.on("console", lambda msg: print(f"[{label} console:{msg.type}] {msg.text}"))
    pg.on("pageerror", lambda err: print(f"[{label} error] {err}"))


async def find_tableau_frame(pg):
    for f in pg.frames:
        if "public.tableau.com" in f.url:
            return f
    return None


def strip_sheet_prefix(text, prefix="snapshot"):
    """Tableau's header cells sometimes include the worksheet name
    ("snapshot") concatenated directly onto the real field name with no
    separator (e.g. "snapshotNamenum" instead of "Namenum"). Which variant
    gets captured depends on which render pass first populated that
    header cell, so strip it defensively rather than relying on capturing
    a "clean" pass."""
    if text.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)].isupper():
        return text[len(prefix):]
    return text


async def scrape():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Stamp with Central time (not UTC) so the filename always matches the
    # intuitive "today" for Dane County, regardless of when this runs. UTC
    # caused manual evening runs to save under tomorrow's date (e.g. 10 PM
    # Central is already 3 AM UTC the next day).
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"jail_snapshot_{today}.csv")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 1550},
        )

        # --- Step 1: discover the real public.tableau.com URL ---
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

        # --- Step 2: navigate directly (first-party, passes WAF like a real user) ---
        page = await context.new_page()
        _attach_debug_listeners(page, "page")
        await page.goto(tableau_url, wait_until="load", timeout=60000)
        await page.wait_for_timeout(5000)
        await page.screenshot(path="debug_direct_tableau_load.png")

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
                "Check debug_selection_failed.png"
            )

        # Open the Download menu, then "Data" (opens the View Data popup)
        await tableau_frame.get_by_role("button", name="Download").click()
        await page.wait_for_timeout(1000)

        async with context.expect_page(timeout=20000) as new_page_info:
            await tableau_frame.get_by_role("menuitem", name="Data").click()
        data_page = await new_page_info.value
        _attach_debug_listeners(data_page, "data_page")
        await data_page.wait_for_timeout(2000)

        # Switch to Full Data tab and select all fields
        await data_page.click("text=Full Data")
        await data_page.wait_for_timeout(1500)
        await data_page.click("text=Show Fields")
        await data_page.wait_for_timeout(1000)
        await data_page.click("text=(All)")
        await data_page.wait_for_timeout(1000)
        await data_page.keyboard.press("Escape")
        await data_page.wait_for_timeout(1000)

        # --- Crank up the rows-per-page box so everything renders at once ---
        # This is the small numeric input near the bottom-left of the Full
        # Data view (defaults to 200).
        candidate = data_page.locator("input").first
        try:
            await candidate.click(click_count=3)  # select existing text
            await candidate.fill(ROW_COUNT_OVERRIDE)
            await candidate.press("Enter")
            await data_page.wait_for_timeout(2000)
            print(f"Set row count input to {ROW_COUNT_OVERRIDE}")
        except Exception as e:
            print(f"Could not set row count input (will rely on scrolling instead): {e}")

        await data_page.screenshot(path="debug_full_data_view.png")

        grid_box = await data_page.evaluate(
            """() => {
                const grid = document.querySelector('[role="grid"]');
                if (!grid) return null;
                const r = grid.getBoundingClientRect();
                return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height};
            }"""
        )
        print("GRID BOX:", grid_box)

        if grid_box is None:
            await data_page.screenshot(path="debug_no_grid_found.png")
            await browser.close()
            raise RuntimeError(
                "Could not find [role='grid'] element at all. "
                "Check debug_no_grid_found.png"
            )

        # --- Scrape the rendered table directly from the DOM ---
        # This grid is custom-virtualized with no native CSS overflow
        # (scrollHeight === clientHeight), so JS scrollTop manipulation is a
        # no-op. It responds to real mouse wheel events instead, driven here
        # via Playwright's mouse.wheel() (genuine trusted input). Rows/columns
        # are anchored by aria-rowindex/aria-colindex so repeated scroll
        # snapshots merge into one matrix instead of producing duplicate or
        # fragmented rows as different column subsets scroll into view.

        async def extract_snapshot():
            return await data_page.evaluate(
                """() => {
                    const out = [];
                    const rows = Array.from(document.querySelectorAll('[role="row"]'));
                    rows.forEach((r, rPos) => {
                        const rowIndexAttr = r.getAttribute('aria-rowindex');
                        const rowIndex = rowIndexAttr !== null ? parseInt(rowIndexAttr, 10) : null;
                        const cells = Array.from(r.querySelectorAll('[role="gridcell"], [role="columnheader"]'));
                        cells.forEach((c, cPos) => {
                            const colIndexAttr = c.getAttribute('aria-colindex');
                            const colIndex = colIndexAttr !== null ? parseInt(colIndexAttr, 10) : null;
                            const isHeader = c.getAttribute('role') === 'columnheader';
                            out.push({
                                rowIndex: rowIndex,
                                rowPos: rPos,
                                colIndex: colIndex,
                                colPos: cPos,
                                isHeader: isHeader,
                                text: c.textContent.trim(),
                            });
                        });
                    });
                    return out;
                }"""
            )

        # Check whether aria-rowindex/aria-colindex are actually present -
        # if not, we fall back to positional indices, which is less robust
        # under virtualization but still better than nothing.
        probe = await extract_snapshot()
        has_aria_index = any(c["rowIndex"] is not None for c in probe) and any(
            c["colIndex"] is not None for c in probe
        )
        print(f"Using aria-rowindex/aria-colindex: {has_aria_index}")

        # matrix[row_key][col_key] = text ; headers[col_key] = header text
        matrix = {}
        headers = {}

        def merge_snapshot(cells):
            added = 0
            for c in cells:
                row_key = c["rowIndex"] if has_aria_index else c["rowPos"]
                col_key = c["colIndex"] if has_aria_index else c["colPos"]
                if row_key is None or col_key is None or not c["text"]:
                    continue
                if c["isHeader"]:
                    if col_key not in headers:
                        headers[col_key] = c["text"]
                        added += 1
                    continue
                row = matrix.setdefault(row_key, {})
                if col_key not in row:
                    row[col_key] = c["text"]
                    added += 1
            return added

        merge_snapshot(probe)

        await data_page.mouse.move(grid_box["x"], grid_box["y"])

        async def sweep_horizontal_at_current_position():
            """Sweep left-to-right at whatever vertical scroll position we're
            currently at, capturing every column for whatever rows are
            visible right now, before moving further down. This is the fix:
            doing this only at a handful of sampled vertical offsets (the
            old approach) left ~700 of 731 rows with only their first ~10
            columns ever captured, since those rows were never visible
            during one of the sparse horizontal-sweep sample points."""
            await data_page.mouse.wheel(-100000, 0)  # reset to left edge
            await data_page.wait_for_timeout(120)
            merge_snapshot(await extract_snapshot())

            stable_rounds = 0
            for _ in range(60):
                await data_page.keyboard.down("Shift")
                await data_page.mouse.wheel(300, 0)
                await data_page.keyboard.up("Shift")
                await data_page.wait_for_timeout(120)
                new_count = merge_snapshot(await extract_snapshot())
                if new_count == 0:
                    stable_rounds += 1
                    if stable_rounds > 4:
                        break
                else:
                    stable_rounds = 0

            # Reset horizontal scroll back to left before continuing the
            # vertical pass, so the next vertical step starts from a known
            # column position.
            await data_page.mouse.wheel(-100000, 0)
            await data_page.wait_for_timeout(120)

        # Combined vertical + horizontal sweep: at every vertical step,
        # fully sweep left-to-right before moving down, so every row gets
        # every column captured regardless of where it happens to render.
        await sweep_horizontal_at_current_position()  # capture row 1's full width first

        stable_rounds = 0
        for i in range(400):
            await data_page.mouse.wheel(0, 300)
            await data_page.wait_for_timeout(150)
            row_count_before = len(matrix)
            await sweep_horizontal_at_current_position()
            new_rows = len(matrix) - row_count_before
            if new_rows == 0:
                stable_rounds += 1
                if stable_rounds > 10:
                    break
            else:
                stable_rounds = 0
            if (i + 1) % 20 == 0:
                print(f"  ...progress: {len(matrix)} rows, {len(headers)} columns so far")

        print(f"After combined sweep: {len(matrix)} rows, {len(headers)} known columns")

        # Strip the Tableau worksheet-name prefix ("snapshot") that
        # sometimes gets concatenated onto header text - see module
        # docstring for why this varies run to run.
        headers = {k: strip_sheet_prefix(v) for k, v in headers.items()}

        if EXPECTED_KEY_COLUMN not in headers.values():
            await data_page.screenshot(path="debug_missing_key_column.png")
            await browser.close()
            raise RuntimeError(
                f"Expected '{EXPECTED_KEY_COLUMN}' column after prefix-stripping, "
                f"but found columns: {sorted(headers.values())}. "
                "The Tableau header prefix pattern may have changed - "
                "check debug_missing_key_column.png."
            )

        # Build final table from the matrix
        sorted_col_keys = sorted(headers.keys())
        header_row = [headers[k] for k in sorted_col_keys]
        sorted_row_keys = sorted(matrix.keys())
        table_data = [header_row]
        for rk in sorted_row_keys:
            row = matrix[rk]
            table_data.append([row.get(ck, "") for ck in sorted_col_keys])

        print(f"Rows extracted from DOM: {len(table_data)}")

        if not table_data or len(table_data) < 2:
            await data_page.screenshot(path="debug_extraction_failed.png")
            await browser.close()
            raise RuntimeError(
                f"Extraction returned too few rows ({len(table_data)}). "
                "Check debug_extraction_failed.png and debug_full_data_view.png "
                "to see what the table actually looked like."
            )

        # table_data[0] is the header row (built from `headers`), the rest
        # are data rows in row-index order.
        header, *data_rows = table_data

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(data_rows)

        print(f"Saved: {output_path} ({len(data_rows)} data rows, {len(header)} columns)")

        await browser.close()
        return output_path


if __name__ == "__main__":
    try:
        path = asyncio.run(scrape())
        print(f"Success: {path}")
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
