import streamlit as st
import pandas as pd
import os
import glob
import re

st.set_page_config(page_title="Dane County Jail Roster Dashboard", layout="wide")

# ── 1. DATA LOADERS (SINGLE FILE & HISTORICAL TRENDS) ─────────────────

DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')

def extract_date(file_path):
    """Pulls the YYYY-MM-DD date out of a filename like dane_jail_2026-06-26.csv.
    Returns None if no date is found (so it can be excluded/sorted last)."""
    match = DATE_RE.search(os.path.basename(file_path))
    return match.group(1) if match else None


@st.cache_data(ttl=600)  # Caches for 10 minutes to keep performance fast
def load_data():
    all_csvs = glob.glob("dane_jail_*.csv")
    timestamped_files = [f for f in all_csvs if "full_scrape" not in f]

    if not timestamped_files:
        if os.path.exists("dane_jail_full_scrape.csv"):
            latest_file = "dane_jail_full_scrape.csv"
        else:
            return pd.DataFrame(), "No files found", []
    else:
        # Sort by the date embedded in the filename, not file mtime.
        # mtime is unreliable on a fresh GitHub Actions checkout, where
        # every file can get the same modification timestamp.
        dated_files = [(f, extract_date(f)) for f in timestamped_files]
        dated_files = [(f, d) for f, d in dated_files if d is not None]
        if dated_files:
            dated_files.sort(key=lambda x: x[1])
            latest_file = dated_files[-1][0]
        else:
            # Fallback: no filenames had parseable dates, use mtime as last resort
            latest_file = max(timestamped_files, key=os.path.getmtime)

    df = pd.read_csv(latest_file)

    # Defensive cleanup against empty or missing data values
    df['charges_str'] = df['charges_str'].fillna("")
    if 'statute_codes' in df.columns:
        df['statute_codes'] = df['statute_codes'].fillna("")
    else:
        df['statute_codes'] = ""
    df['arrest_agencies'] = df['arrest_agencies'].fillna("Unknown Agency")
    df['charge_level'] = df['charge_level'].fillna("Unknown")
    df['total_charge_counts'] = df['total_charge_counts'].fillna(0).astype(int)
    df['booking_date'] = df['booking_date'].fillna("Unknown Date")

    return df, latest_file, timestamped_files


@st.cache_data(ttl=600)
def process_historical_trends(timestamped_files):
    """Loops through all historical daily files to build trend data for the graph"""
    history_records = []

    for file_path in timestamped_files:
        try:
            date_str = extract_date(file_path)
            if date_str is None:
                continue  # skip files we can't date

            day_df = pd.read_csv(file_path)

            total_pop = len(day_df)
            felonies = len(day_df[day_df['charge_level'] == 'Felony']) if 'charge_level' in day_df.columns else 0
            misdemeanors = len(day_df[day_df['charge_level'] == 'Misdemeanor']) if 'charge_level' in day_df.columns else 0
            civil = len(day_df[day_df['charge_level'] == 'Civil']) if 'charge_level' in day_df.columns else 0

            history_records.append({
                "Date": date_str,
                "Total Population": total_pop,
                "Felony Holds": felonies,
                "Misdemeanors": misdemeanors,
                "Civil / Traffic": civil
            })
        except Exception:
            pass  # Keep moving if a single file is corrupt or empty

    if history_records:
        trend_df = pd.DataFrame(history_records)
        # Sort chronologically by the actual date string (YYYY-MM-DD sorts correctly as text)
        trend_df = trend_df.sort_values("Date")
        # Drop accidental duplicate dates (e.g. two scrapes same day), keep the last
        trend_df = trend_df.drop_duplicates(subset="Date", keep="last")
        return trend_df
    return pd.DataFrame()


def agency_profile_table(df):
    """Builds a per-agency breakdown of inmate count and charge-level mix.
    An inmate can list multiple agencies; this counts them under each
    agency they're associated with (not mutually exclusive)."""
    rows = []
    unique_agencies = set()
    for agency_str in df['arrest_agencies'].unique():
        for a in str(agency_str).split(";"):
            a = a.strip()
            if a and a != "Unknown Agency":
                unique_agencies.add(a)

    for agency in sorted(unique_agencies):
        mask = df['arrest_agencies'].str.contains(re.escape(agency), na=False)
        sub = df[mask]
        n = len(sub)
        if n == 0:
            continue
        vc = sub['charge_level'].value_counts()
        felony_pct = round(100 * vc.get('Felony', 0) / n)
        misd_pct = round(100 * vc.get('Misdemeanor', 0) / n)
        civil_pct = round(100 * vc.get('Civil', 0) / n)
        rows.append({
            "Agency": agency,
            "Inmates": n,
            "Felony %": felony_pct,
            "Misdemeanor %": misd_pct,
            "Civil %": civil_pct,
        })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows).sort_values("Inmates", ascending=False).reset_index(drop=True)
    return out


# Execute Data Accumulation
df, file_source, historical_file_list = load_data()

if df.empty:
    st.error("No data files found in the repository workspace. Please run your scraper first.")
    st.stop()


# ── 2. HEADER & KPI METRICS ──────────────────────────────────────────
st.title("Dane County Jail Roster Analysis")
st.caption(f"Active Workspace File: `{file_source}`")

total_inmates = len(df)
felonies = len(df[df['charge_level'] == 'Felony'])
misdemeanors = len(df[df['charge_level'] == 'Misdemeanor'])
civil_holds = len(df[df['charge_level'] == 'Civil'])
unknowns = len(df[df['charge_level'] == 'Unknown'])

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Inmates", total_inmates)
m2.metric("Felony Holds", felonies)
m3.metric("Misdemeanors", misdemeanors)
m4.metric("Civil / Traffic", civil_holds)
m5.metric("Unmapped Charges", unknowns)

st.markdown("---")


# ── 3. VISUAL HISTORICAL TRENDS GRAPH ─────────────────────────────────
st.subheader("📈 Population Trends Over Time")

trend_df = process_historical_trends(historical_file_list)

if not trend_df.empty and len(trend_df) > 1:
    track_options = ["Total Population", "Felony Holds", "Misdemeanors", "Civil / Traffic"]
    selected_metrics = st.multiselect("Select metrics to plot:", track_options, default=["Total Population", "Felony Holds", "Civil / Traffic"])

    if selected_metrics:
        chart_data = trend_df.set_index("Date")[selected_metrics]
        st.line_chart(chart_data, use_container_width=True)
    else:
        st.warning("Please select at least one metric to display the graph.")

    with st.expander("View raw trend data"):
        st.dataframe(trend_df, use_container_width=True)
else:
    st.info("📊 Graph tracking requires at least two distinct daily timestamped files to plot a trend line.")

st.markdown("---")


# ── 4. AGENCY CHARGE PROFILES ─────────────────────────────────────────
st.subheader("🚔 Agency Charge Profiles")
st.caption("Breakdown of arresting agencies by how many inmates they're associated with and the severity mix of those inmates' charges. An inmate listing multiple agencies is counted under each.")

agency_df = agency_profile_table(df)

if not agency_df.empty:
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.dataframe(agency_df, use_container_width=True, hide_index=True)
    with col_b:
        top_n = agency_df.head(10).set_index("Agency")["Inmates"]
        st.bar_chart(top_n, use_container_width=True)
else:
    st.info("No agency data available in this snapshot.")

st.markdown("---")


# ── 5. SIDEBAR FILTERS ───────────────────────────────────────────────
st.sidebar.header("Filter Options")

search_query = st.sidebar.text_input("Search Charge Descriptions", "").strip().upper()
severity_options = ["All"] + sorted(list(df['charge_level'].unique()))
selected_severity = st.sidebar.selectbox("Filter by Severity Level", severity_options)

unique_agencies = set()
for agency_str in df['arrest_agencies'].unique():
    for a in str(agency_str).split(";"):
        if a.strip() and a.strip() != "Unknown Agency":
            unique_agencies.add(a.strip())
agency_options = ["All"] + sorted(list(unique_agencies))
selected_agency = st.sidebar.selectbox("Filter by Arresting Agency", agency_options)

# Apply active filters
filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['charges_str'].str.contains(search_query, na=False)]

if selected_severity != "All":
    filtered_df = filtered_df[filtered_df['charge_level'] == selected_severity]

if selected_agency != "All":
    filtered_df = filtered_df[filtered_df['arrest_agencies'].str.contains(re.escape(selected_agency), na=False)]


# ── 6. MAIN ROSTER TABLE ─────────────────────────────────────────────
st.subheader(f"Current Bookings Roster ({len(filtered_df)} Matching Records)")

display_cols = ['booking_date', 'charge_level', 'total_charge_counts', 'arrest_agencies']
st.dataframe(
    filtered_df[display_cols].rename(columns={
        'booking_date': 'Booking Date / Time',
        'charge_level': 'Highest Severity',
        'total_charge_counts': 'Total Charge Counts',
        'arrest_agencies': 'Arresting Agency'
    }),
    use_container_width=True
)

st.markdown("---")


# ── 7. DEEP DIVE VIEW (ZIP ALIGNMENT) ────────────────────────────────
st.subheader("Inmate Profile Deep-Dive")

inmate_options = []
for idx, row in filtered_df.iterrows():
    primary_charge = str(row['charges_str']).split(';')[0].strip()
    primary_charge = primary_charge if primary_charge else "No Charge Listed"
    label = f"{row['booking_date']} | {primary_charge} ({row['charge_level']})"
    inmate_options.append((idx, label))

if inmate_options:
    option_dict = dict(inmate_options)
    selected_idx = st.selectbox(
        "Select an inmate profile to extract:",
        options=list(option_dict.keys()),
        format_func=lambda x: option_dict[x]
    )

    inmate_data = filtered_df.loc[selected_idx]

    raw_charges = [c.strip() for c in str(inmate_data['charges_str']).split(';') if c.strip()]
    raw_statutes = [s.strip() for s in str(inmate_data['statute_codes']).split(';')]

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("#### Aligned Rap Sheet")
        if not raw_charges:
            st.write("*No itemized charges found.*")
        for i, charge in enumerate(raw_charges):
            statute_code = "None Listed"
            if i < len(raw_statutes) and raw_statutes[i]:
                statute_code = raw_statutes[i]

            st.markdown(f"**{i+1}. {charge}**")
            st.caption(f"Statute Mapping: `{statute_code}`")
            st.markdown("")

    with col2:
        st.markdown("#### Administrative Metadata")
        st.write(f"**Initial Booking:** {inmate_data['booking_date']}")
        st.write(f"**Assessed Tier:** {inmate_data['charge_level']}")
        st.write(f"**Responding Agencies:** {inmate_data['arrest_agencies']}")
        st.write(f"**Aggregated Counts:** {inmate_data['total_charge_counts']}")
        st.markdown("---")
        st.markdown(f"[🔗 Open Original Dane Co. Sheriff Link]({inmate_data['url']})")
else:
    st.warning("No records matched your sidebar filter configurations.")
