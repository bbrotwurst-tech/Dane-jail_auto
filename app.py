import streamlit as st
import pandas as pd
import os
import glob

st.set_page_config(page_title="Dane County Jail Roster Dashboard", layout="wide")

# ── 1. DATA LOADERS (SINGLE FILE & HISTORICAL TRENDS) ─────────────────
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
        # Grab the newest individual file for the main roster view
        latest_file = max(timestamped_files, key=os.path.getmtime)
    
    df = pd.read_csv(latest_file)
    
    # Defensive cleanup against empty or missing data values
    df['charges_str'] = df['charges_str'].fillna("")
    df['statute_codes'] = df['statute_codes'].fillna("")
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
            # Extract the raw date string from the filename (e.g., '2026-06-26')
            filename = os.path.basename(file_path)
            date_str = filename.replace("dane_jail_", "").replace(".csv", "")
            
            # Read the file to aggregate metrics for that specific day
            day_df = pd.read_csv(file_path)
            
            total_pop = len(day_df)
            felonies = len(day_df[day_df['charge_level'] == 'Felony']) if 'charge_level' in day_df.columns else 0
            misdemeanors = len(day_df[day_df['charge_level'] == 'Misdemeanor']) if 'charge_level' in day_df.columns else 0
            civil = len(day_df[day_df['charge_level'] == 'Civil']) if 'charge_level' in day_df.columns else 0
            
            # FIX: Included "Civil / Traffic" in the daily extraction dictionary
            history_records.append({
                "Date": date_str,
                "Total Population": total_pop,
                "Felony Holds": felonies,
                "Misdemeanors": misdemeanors,
                "Civil / Traffic": civil
            })
        except Exception:
            pass # Keep moving if a single file is corrupt or empty
            
    if history_records:
        trend_df = pd.DataFrame(history_records)
        # Sort chronologically by the date string
        trend_df = trend_df.sort_values("Date")
        return trend_df
    return pd.DataFrame()

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


# ── 3. VISUAL HISTORICAL TRENDS GRAPH (WITH FIXED CIVIL METRIC) ──────
st.subheader("📈 Population Trends Over Time")

trend_df = process_historical_trends(historical_file_list)

if not trend_df.empty and len(trend_df) > 1:
    # FIX: Added "Civil / Traffic" directly to the options list
    track_options = ["Total Population", "Felony Holds", "Misdemeanors", "Civil / Traffic"]
    selected_metrics = st.multiselect("Select metrics to plot:", track_options, default=["Total Population", "Felony Holds", "Civil / Traffic"])
    
    if selected_metrics:
        # Create a clean line chart mapping metrics against the Date index
        chart_data = trend_df.set_index("Date")[selected_metrics]
        st.line_chart(chart_data, use_container_width=True)
    else:
        st.warning("Please select at least one metric to display the graph.")
else:
    st.info("📊 Graph tracking requires at least two distinct daily timestamped files to plot a trend line.")

st.markdown("---")


# ── 4. SIDEBAR FILTERS ───────────────────────────────────────────────
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
    filtered_df = filtered_df[filtered_df['arrest_agencies'].str.contains(selected_agency, na=False)]


# ── 5. MAIN ROSTER TABLE ─────────────────────────────────────────────
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


# ── 6. DEEP DIVE VIEW (ZIP ALIGNMENT) ────────────────────────────────
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
