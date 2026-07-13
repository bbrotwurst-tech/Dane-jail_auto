import streamlit as st
import pandas as pd
import os
import glob
import re

from time_series_analysis import render_time_series_section
from location_treemap import render_location_treemap
from location_trends import render_location_trends

st.set_page_config(page_title="Jail IQ | Dane County", layout="wide")

# ── County selector ────────────────────────────────────────────────
page = st.sidebar.radio("Select County", ["Dane County", "Columbia County"])

# ── Ko-fi support link (sidebar) — shown on both tabs ─────────────────
KOFI_USERNAME = "bbrotwursttech"
st.sidebar.markdown("---")
st.sidebar.markdown(
    f"""
    <a href="https://ko-fi.com/{KOFI_USERNAME}" target="_blank">
        <img src="https://storage.ko-fi.com/cdn/kofi5.png?v=3"
             alt="Support this project on Ko-fi"
             style="border:0px; height:36px; width: auto; margin-bottom: 6px;">
    </a>
    """,
    unsafe_allow_html=True
)
st.sidebar.caption("Free & open project — tips help cover hosting/dev time.")

if page == "Columbia County":
    from columbia_tab import render_columbia_tab
    render_columbia_tab()
    st.stop()

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
    timestamped_files = [
        f for f in all_csvs
        # NOTE: 2026-06-25 excluded -- confirmed bad scrape for that date.
        # Remove this exclusion once/if a corrected file replaces it.
        if "full_scrape" not in f and "2026-06-25" not in f
    ]

    if not timestamped_files:
        if os.path.exists("dane_jail_full_scrape.csv"):
            latest_file = "dane_jail_full_scrape.csv"
        else:
            return pd.DataFrame(), "No files found", [], None
    else:
        dated_files = [(f, extract_date(f)) for f in timestamped_files]
        dated_files = [(f, d) for f, d in dated_files if d is not None]
        if dated_files:
            dated_files.sort(key=lambda x: x[1])
            latest_file = dated_files[-1][0]
        else:
            latest_file = max(timestamped_files, key=os.path.getmtime)

    df = pd.read_csv(latest_file)

    df['charges_str'] = df['charges_str'].fillna("")
    if 'statute_codes' in df.columns:
        df['statute_codes'] = df['statute_codes'].fillna("")
    else:
        df['statute_codes'] = ""
    df['arrest_agencies'] = df['arrest_agencies'].fillna("Unknown Agency")
    df['charge_level'] = df['charge_level'].fillna("Unknown")
    df['total_charge_counts'] = df['total_charge_counts'].fillna(0).astype(int)
    df['booking_date'] = df['booking_date'].fillna("Unknown Date")
    if 'url' not in df.columns:
        df['url'] = ""
    df['url'] = df['url'].fillna("")

    latest_date_str = extract_date(latest_file)

    return df, latest_file, timestamped_files, latest_date_str


def get_latest_merged_file(merged_dir="merged"):
    """Finds the most recent merged_jail_data_YYYY-MM-DD.csv file, by date in
    the filename (not file mtime), so it stays correct regardless of when
    files were downloaded/committed."""
    files = glob.glob(os.path.join(merged_dir, "merged_jail_data_*.csv"))
    dated = [(f, extract_date(f)) for f in files]
    dated = [(f, d) for f, d in dated if d is not None]
    if not dated:
        return None
    dated.sort(key=lambda x: x[1])
    return dated[-1][0]


@st.cache_data(ttl=600)
def process_historical_trends(timestamped_files):
    history_records = []
    for file_path in timestamped_files:
        try:
            date_str = extract_date(file_path)
            if date_str is None:
                continue
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
            pass
    if history_records:
        trend_df = pd.DataFrame(history_records)
        trend_df = trend_df.sort_values("Date")
        trend_df = trend_df.drop_duplicates(subset="Date", keep="last")
        return trend_df
    return pd.DataFrame()


@st.cache_data(ttl=600)
def compute_turnover(timestamped_files):
    dated_files = [(f, extract_date(f)) for f in timestamped_files]
    dated_files = [(f, d) for f, d in dated_files if d is not None]
    dated_files.sort(key=lambda x: x[1])

    if len(dated_files) < 2:
        return pd.DataFrame()

    records = []
    prev_urls, prev_date = None, None

    for f, date_str in dated_files:
        try:
            day_df = pd.read_csv(f)
            if 'url' not in day_df.columns:
                continue
            cur_urls = set(day_df['url'].dropna())
        except Exception:
            continue

        if prev_urls is not None:
            exited = len(prev_urls - cur_urls)
            booked = len(cur_urls - prev_urls)
            records.append({
                "Transition": f"{prev_date} -> {date_str}",
                "Exited": exited,
                "Booked": booked,
            })

        prev_urls, prev_date = cur_urls, date_str

    return pd.DataFrame(records)


def parse_charge_list(charges_str):
    if not charges_str or pd.isna(charges_str):
        return []
    parts = [c.strip().upper() for c in str(charges_str).split(';') if c.strip()]
    return [re.sub(r'\s*\(\d+\s*CT\)\s*$', '', p).strip() for p in parts]


def top_charges_table(df, level_filter=None, top_n=15):
    rows = []
    for _, row in df.iterrows():
        if level_filter and row['charge_level'] != level_filter:
            continue
        for charge in parse_charge_list(row['charges_str']):
            if charge:
                rows.append(charge)

    if not rows:
        return pd.DataFrame()

    counts = pd.Series(rows).value_counts().head(top_n)
    out = counts.reset_index()
    out.columns = ["Charge", "Count"]
    return out


def compute_stay_length(df, as_of_date_str):
    df = df.copy()
    # Booking dates sometimes come through with no space between the
    # year and the time, e.g. "5/30/202612:29 AM" instead of
    # "5/30/2026 12:29 AM". Insert a space before AM/PM clock times so
    # pd.to_datetime can actually parse them instead of returning NaT.
    fixed_dates = df['booking_date'].astype(str).str.replace(
        r'(\d{4})(\d{1,2}:\d{2})', r'\1 \2', regex=True
    )
    df['_booking_dt'] = pd.to_datetime(fixed_dates, errors='coerce')
    try:
        ref_date = pd.Timestamp(as_of_date_str)
    except Exception:
        ref_date = pd.Timestamp.now()
    df['_days_held'] = (ref_date - df['_booking_dt']).dt.days
    valid = df[(df['_days_held'] >= 0) & (df['_days_held'] <= 3650)]
    return valid, valid['_days_held']


JUDICIAL_GROUPS = {
    "pretrial": ["pretrial", "prearraignment", "prearr", "presentence"],
    "sentenced": ["sentenced"],
    "supervision": ["p/p viol", "e.s. sanct", "probation violation", "parole violation", "extended supervision"],
    "hold": ["writ", "intransit", "extradition"],
}

def classify_judicial_status(status):
    if not status or pd.isna(status):
        return "Other"
    s = str(status).lower()
    for group, keywords in JUDICIAL_GROUPS.items():
        if any(kw in s for kw in keywords):
            return group.capitalize()
    return "Other"


def agency_profile_table(df):
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
df, file_source, historical_file_list, latest_date_str = load_data()

if df.empty:
    st.error("No data files found in the repository workspace. Please run your scraper first.")
    st.stop()


# ── 2. HEADER & KPI METRICS ──────────────────────────────────────────
st.title("Jail IQ")
st.caption("Dane County Jail Roster Analytics")
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
st.subheader("Population Trends Over Time")

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
    st.info("Graph tracking requires at least two distinct daily timestamped files to plot a trend line.")

turnover_df = compute_turnover(historical_file_list)

if not turnover_df.empty:
    st.markdown("##### Daily Turnover")
    st.caption("Comparing each day's roster to the prior day's roster by detail URL. 'Exited' may include releases, transfers to DOC custody, or transfers to another facility -- the roster alone can't distinguish which.")

    col_t1, col_t2 = st.columns([2, 1])
    with col_t1:
        st.bar_chart(turnover_df.set_index("Transition")[["Booked", "Exited"]], use_container_width=True)
    with col_t2:
        avg_booked = turnover_df["Booked"].mean()
        avg_exited = turnover_df["Exited"].mean()
        st.metric("Avg Daily Bookings", f"{avg_booked:.1f}")
        st.metric("Avg Daily Exits", f"{avg_exited:.1f}")

st.markdown("---")


# ── 3.6 LOCATION BREAKDOWN (building/unit treemap + trends over time) ──
st.subheader("Where residents are housed")

latest_merged_path = get_latest_merged_file()
if latest_merged_path:
    latest_merged_df = pd.read_csv(latest_merged_path)
    render_location_treemap(latest_merged_df)

    st.markdown("##### Location trends over time")
    render_location_trends("merged")
else:
    st.info("No merged location data found yet. Run the merge pipeline to populate the `merged/` folder.")

st.markdown("---")


# ── 3.5 TIME SERIES ANALYSIS (rolling avgs, day-of-week, charge mix,
#         stay-length trend, agency activity over time) ───────────────
render_time_series_section(
    trend_df, turnover_df, historical_file_list,
    extract_date, compute_stay_length
)


# ── 4. LENGTH OF STAY ──────────────────────────────────────────────────
st.subheader("Length of Stay")
st.caption(f"Based on booking date vs. snapshot date ({latest_date_str or 'unknown'}). Excludes records with missing or unparseable booking dates.")

stay_df, days_held_series = compute_stay_length(df, latest_date_str)

if not days_held_series.empty:
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Median Stay", f"{days_held_series.median():.0f}d")
    s2.metric("Mean Stay", f"{days_held_series.mean():.0f}d")
    s3.metric("Longest Stay", f"{days_held_series.max():.0f}d")
    s4.metric("Booked < 7 Days Ago", int((days_held_series < 7).sum()))

    with st.expander("View stay length distribution"):
        bins = pd.cut(days_held_series, bins=[0, 7, 30, 90, 180, 365, 100000],
                       labels=["<7d", "7-30d", "30-90d", "90-180d", "180-365d", "1yr+"])
        bin_counts = bins.value_counts().sort_index()
        st.bar_chart(bin_counts, use_container_width=True)

    with st.expander("Stay length by charge severity"):
        severity_stats = []
        for level in ["Felony", "Misdemeanor", "Civil", "Unknown"]:
            level_mask = stay_df['charge_level'] == level
            level_days = stay_df.loc[level_mask, '_days_held']
            if len(level_days) > 0:
                severity_stats.append({
                    "Severity": level,
                    "Count": len(level_days),
                    "Median Stay (d)": round(level_days.median()),
                    "Mean Stay (d)": round(level_days.mean(), 1),
                    "Longest Stay (d)": int(level_days.max()),
                })
        if severity_stats:
            severity_stay_df = pd.DataFrame(severity_stats)
            st.dataframe(severity_stay_df, use_container_width=True, hide_index=True)
            st.bar_chart(severity_stay_df.set_index("Severity")["Median Stay (d)"], use_container_width=True)
        else:
            st.info("Not enough data to break down stay length by severity.")
else:
    st.info("No valid booking dates found to compute length of stay.")

st.markdown("---")


# ── 5. TOP CHARGES ─────────────────────────────────────────────────────
st.subheader("Top Charges")
st.caption("Note: Felony/Misdemeanor/Civil filters below reflect the INMATE's overall (highest) charge level, not the individual charge's own level. An inmate classified Felony may still have misdemeanor charges counted in the 'Felony' tab if they're also charged with a felony elsewhere on their sheet.")

charge_tab_all, charge_tab_felony, charge_tab_misd, charge_tab_civil = st.tabs(
    ["All Inmates", "Felony Inmates", "Misdemeanor Inmates", "Civil Inmates"]
)

with charge_tab_all:
    t = top_charges_table(df, level_filter=None)
    if not t.empty:
        st.bar_chart(t.set_index("Charge")["Count"], use_container_width=True)
        st.dataframe(t, use_container_width=True, hide_index=True)
    else:
        st.info("No charge data available.")

with charge_tab_felony:
    t = top_charges_table(df, level_filter="Felony")
    if not t.empty:
        st.bar_chart(t.set_index("Charge")["Count"], use_container_width=True)
        st.dataframe(t, use_container_width=True, hide_index=True)
    else:
        st.info("No felony-tagged inmates in this snapshot.")

with charge_tab_misd:
    t = top_charges_table(df, level_filter="Misdemeanor")
    if not t.empty:
        st.bar_chart(t.set_index("Charge")["Count"], use_container_width=True)
        st.dataframe(t, use_container_width=True, hide_index=True)
    else:
        st.info("No misdemeanor-tagged inmates in this snapshot.")

with charge_tab_civil:
    t = top_charges_table(df, level_filter="Civil")
    if not t.empty:
        st.bar_chart(t.set_index("Charge")["Count"], use_container_width=True)
        st.dataframe(t, use_container_width=True, hide_index=True)
    else:
        st.info("No civil-tagged inmates in this snapshot.")

st.markdown("---")


# ── 6. JUDICIAL STATUS BREAKDOWN ──────────────────────────────────────
st.subheader("Judicial Status Breakdown")

if 'judicial_status' in df.columns:
    status_df = df.copy()
    status_df['status_group'] = status_df['judicial_status'].apply(classify_judicial_status)

    j1, j2 = st.columns([1, 2])
    with j1:
        group_counts = status_df['status_group'].value_counts()
        st.bar_chart(group_counts, use_container_width=True)
        for group, count in group_counts.items():
            pct = 100 * count / len(status_df)
            st.write(f"**{group}**: {count} ({pct:.1f}%)")

    with j2:
        detail_counts = status_df['judicial_status'].value_counts().reset_index()
        detail_counts.columns = ["Judicial Status", "Count"]
        st.dataframe(detail_counts, use_container_width=True, hide_index=True, height=400)
else:
    st.info("No `judicial_status` column found in this data source.")

st.markdown("---")


# ── 7. AGENCY CHARGE PROFILES ─────────────────────────────────────────
st.subheader("Agency Charge Profiles")
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


# ── 8. SIDEBAR FILTERS ───────────────────────────────────────────────
st.sidebar.header("Filter Options")

search_query = st.sidebar.text_input("Search Charge Descriptions", "").strip().upper()
severity_options = ["All"] + sorted(list(df['charge_level'].unique()))
selected_severity = st.sidebar.selectbox("Filter by Severity Level", severity_options)

unique_agencies_sidebar = set()
for agency_str in df['arrest_agencies'].unique():
    for a in str(agency_str).split(";"):
        if a.strip() and a.strip() != "Unknown Agency":
            unique_agencies_sidebar.add(a.strip())
agency_options = ["All"] + sorted(list(unique_agencies_sidebar))
selected_agency = st.sidebar.selectbox("Filter by Arresting Agency", agency_options)

filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['charges_str'].str.contains(search_query, na=False)]

if selected_severity != "All":
    filtered_df = filtered_df[filtered_df['charge_level'] == selected_severity]

if selected_agency != "All":
    filtered_df = filtered_df[filtered_df['arrest_agencies'].str.contains(re.escape(selected_agency), na=False)]


# ── 9. MAIN ROSTER TABLE ─────────────────────────────────────────────
st.subheader(f"Current Bookings Roster ({len(filtered_df)} Matching Records)")

display_cols = ['booking_date', 'charge_level', 'total_charge_counts', 'arrest_agencies', 'url']
st.dataframe(
    filtered_df[display_cols].rename(columns={
        'booking_date': 'Booking Date / Time',
        'charge_level': 'Highest Severity',
        'total_charge_counts': 'Total Charge Counts',
        'arrest_agencies': 'Arresting Agency',
        'url': 'Source'
    }),
    use_container_width=True,
    column_config={
        "Source": st.column_config.LinkColumn(
            "Source",
            display_text="View on danesheriff.com"
        )
    }
)

st.markdown("---")


# ── 10. DEEP DIVE VIEW (ZIP ALIGNMENT) ────────────────────────────────
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
        # FIX: guard against missing/blank url instead of assuming it's always present
        inmate_url = inmate_data.get('url', '')
        if inmate_url and str(inmate_url).strip() and str(inmate_url).lower() != 'nan':
            st.markdown(f"[Open Original Dane Co. Sheriff Link]({inmate_url})")
        else:
            st.caption("No source link available for this record.")
else:
    st.warning("No records matched your sidebar filter configurations.")

# ── Footer note ────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Built and maintained independently. "
    f"[☕ Support this project](https://ko-fi.com/{KOFI_USERNAME}) if you find it useful."
)

