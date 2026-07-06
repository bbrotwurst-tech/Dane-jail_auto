import re
import pdfplumber
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

PDF_PATH = "webdailybookings.pdf"  # overwritten weekly by the download step
OUTPUT_CSV = "columbia_bookings_log.csv"

# ── 1. EXTRACT RAW TEXT (all pages concatenated) ─────────────────────
def extract_full_text(pdf_path):
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # x_tolerance=1 prevents words from being jammed together
            # (a quirk of this report's font spacing)
            page_text = page.extract_text(x_tolerance=1)
            if page_text:
                full_text += page_text + "\n"
    return full_text


# ── 2. SPLIT INTO INDIVIDUAL BOOKING RECORDS ──────────────────────────
# Each record starts with "Date/Time:" and runs until the next one.
RECORD_SPLIT_RE = re.compile(r"(?=Date/Time:\s+\d{2}:\d{2}:\d{2}\s+\d{2}/\d{2}/\d{2})")

# Field patterns within a record
NAME_RE = re.compile(r"Inmate Name:\s+(.+?)\n")
NAME_NUMBER_RE = re.compile(r"Name Number:\s+(\d+)")
AGE_RE = re.compile(r"Age:\s+(\d+)")
ADDRESS_RE = re.compile(r"Address:\s+(.+?)\s+Booking Type:")
BOOKING_TYPE_RE = re.compile(r"Booking Type:\s+(.+?)(?:\nOffense Date|\n\n|$)", re.DOTALL)
DATETIME_RE = re.compile(r"Date/Time:\s+(\d{2}:\d{2}:\d{2}\s+\d{2}/\d{2}/\d{2})")

# Offense table rows: TIME DATE STATUTE DESCRIPTION
# Time may be redacted as **:**:** **/**/****
OFFENSE_ROW_RE = re.compile(
    r"(\*\*:\*\*:\*\*\s+\*\*/\*\*/\*\*\*\*|\d{2}:\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4})\s+"
    r"(\S+)\s+"
    r"(.+)"
)

# Lines to ignore when scanning for offense rows (repeated headers/footers)
NOISE_LINES = (
    "Offense Date", "Statute", "Offense Description",
    "Booking Summary Report", "Columbia County Sheriff",
    "rpjlbsr", "Total Inmates", "Report Includes", "Page "
)


def parse_record(record_text):
    dt_match = DATETIME_RE.search(record_text)
    name_match = NAME_RE.search(record_text)
    if not dt_match or not name_match:
        return None  # malformed / not a real record

    booking_datetime = dt_match.group(1)
    name = name_match.group(1).strip()

    name_number_match = NAME_NUMBER_RE.search(record_text)
    age_match = AGE_RE.search(record_text)
    address_match = ADDRESS_RE.search(record_text)
    booking_type_match = BOOKING_TYPE_RE.search(record_text)

    name_number = name_number_match.group(1) if name_number_match else None
    age = age_match.group(1) if age_match else None
    address = address_match.group(1).strip() if address_match else None

    booking_type = None
    if booking_type_match:
        # Collapse any line-wrapped booking type (e.g. "Violation of Probation /\nParole")
        booking_type = " ".join(booking_type_match.group(1).split())

    # Pull offense rows: everything after "Offense Description" header
    offenses = []
    statutes = []
    lines = record_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped or any(stripped.startswith(n) for n in NOISE_LINES):
            continue
        row_match = OFFENSE_ROW_RE.match(stripped)
        if row_match:
            _, statute, description = row_match.groups()
            statutes.append(statute)
            offenses.append(description.strip())

    return {
        "name_number": name_number,
        "inmate_name": name,
        "age": age,
        "address": address,
        "booking_datetime": booking_datetime,
        "booking_type": booking_type,
        "statutes": "; ".join(statutes),
        "offenses": "; ".join(offenses),
        "offense_count": len(offenses),
    }


def parse_pdf(pdf_path):
    full_text = extract_full_text(pdf_path)
    raw_records = RECORD_SPLIT_RE.split(full_text)

    parsed = []
    for raw in raw_records:
        record = parse_record(raw)
        if record:
            parsed.append(record)
    return pd.DataFrame(parsed)


# ── 3. DEDUPLICATE AGAINST EXISTING LOG ───────────────────────────────
def merge_with_existing(new_df, existing_csv_path):
    try:
        existing_df = pd.read_csv(existing_csv_path)
    except FileNotFoundError:
        existing_df = pd.DataFrame(columns=new_df.columns)

    # Unique key: name_number + booking_datetime uniquely identifies a booking event
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined["dedup_key"] = (
        combined["name_number"].astype(str) + "_" + combined["booking_datetime"].astype(str)
    )
    combined = combined.drop_duplicates(subset="dedup_key", keep="first")
    combined = combined.drop(columns="dedup_key")
    return combined


# ── 4. PIPELINE ORCHESTRATOR ──────────────────────────────────────────
def main():
    print("Parsing Columbia County bookings PDF...")
    new_df = parse_pdf(PDF_PATH)
    print(f"Parsed {len(new_df)} booking records from this PDF.")

    if new_df.empty:
        print("No records parsed — check PDF format hasn't changed.")
        return

    merged_df = merge_with_existing(new_df, OUTPUT_CSV)
    added = len(merged_df) - (len(merged_df) - len(new_df))  # rough diff for logging
    merged_df.to_csv(OUTPUT_CSV, index=False)

    timestamp = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M")
    print(f"[{timestamp}] Total records in log: {len(merged_df)}")


if __name__ == "__main__":
    main()

