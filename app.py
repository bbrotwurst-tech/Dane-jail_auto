import streamlit as st
import pandas as pd
import os
import glob

st.set_page_config(page_title="Dane County Jail Roster Dashboard", layout="wide")

# ── 1. LOAD DATA SAFELY (STRICT TIMESTAMP PRIORITIZATION) ────────────
@st.cache_data(ttl=600)  # Caches data for 10 minutes to keep the app fast
def load_data():
    # Grab all files starting with dane_jail_
    all_csvs = glob.glob("dane_jail_*.csv")
    
    # Filter: Only keep files that DO NOT contain "full_scrape"
    # This isolates true daily files like 'dane_jail_2026-06-26.csv'
    timestamped_files = [f for f in all_csvs if "full_scrape" not in f]
    
    if not timestamped_files:
        # Fallback to the full scrape master file ONLY if no daily files exist
        if os.path.exists("dane_jail_full_scrape.csv"):
            latest_file = "dane_jail_full_scrape.csv"
        else:
            return pd.DataFrame(), "No files found"
    else:
        # Pick the absolute newest timestamped daily file based on disk write time
        latest_file = max(timestamped_files, key=os.path.getmtime)
    
    df = pd.read_csv(latest_file)
    
    # Defensive parsing: convert NaNs to clean defaults so string splits don't crash
    df['charges_str'] = df['charges_str'].fillna("")
    df['statute_codes'] = df['statute_codes'].fillna("")
    df['arrest_agencies'] = df['arrest_agencies'].fillna("Unknown Agency")
    df['charge_level'] = df['charge_level'].fillna("Unknown")
    df['total_charge_counts'] = df['total_charge_counts'].fillna(0).astype(int)
    df['booking_date'] = df['booking_date'].fillna("Unknown Date")
    
    return df, latest_file

df, file_source = load_data()

if df.empty:
    st.error("No data files found! Please run your scraper first to generate the CSV.")
    st.stop()


# ── 2. HEADER & KPI METRICS ──────────────────────────────────────────
st.title("Dane County Jail Roster Analysis")
st.caption(f"Active Data Source: `{file_source}`")

# Calculate high-level roster metrics
total_inmates = len(df)
felonies = len(df[df['charge_level'] == 'Felony'])
misdemeanors = len(df[df['charge_level'] == 'Microdemeanor']) or len(df[df['charge_level'] == 'Misdemeanor'])
civil_holds = len(df[df['charge_level'] == 'Civil'])
unknowns = len(df[df['charge_level'] == 'Unknown'])

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Inmates", total_inmates)
m2.metric("Felony Holds", felonies)
m3.metric("Misdemeanors", misdemeanors)
m4.metric("Civil / Traffic", civil_holds)
m5.metric("Unmapped Charges", unknowns)

st.markdown("---")


# ── 3. SIDEBAR FILTERS & INTERACTION ─────────────────────────────────
st.sidebar.header("Filter Options")

# Text search through charge descriptions
search_query = st.sidebar.text_input("Search Charge Descriptions", "").strip().upper()

# Severity Dropdown
severity_options = ["All"] + sorted(list(df['charge_level'].unique()))
selected_severity = st.sidebar.selectbox("Filter by Severity Level", severity_options)

# Agency Dropdown (Parses individual agencies out of aggregated semicolon strings)
unique_agencies = set()
for agency_str in df['arrest_agencies'].unique():
    for a in agency_str.split(";"):
        if a.strip():
            unique_agencies.add(a.strip())
agency_options = ["All"] + sorted(list(unique_agencies))
selected_agency = st.sidebar.selectbox("Filter by Arresting Agency", agency_options)

# Apply active filtering to the dataframe copy
filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['charges_str'].str.contains(search_query, na=False)]

if selected_severity != "All":
    filtered_df = filtered_df[filtered_df['charge_level'] == selected_severity]

if selected_agency != "All":
    filtered_df = filtered_df[filtered_df['arrest_agencies'].str.contains(selected_agency, na=False)]


# ── 4. PRIMARY ROSTER OVERVIEW TABLE ─────────────────────────────────
st.subheader(f"Current Bookings Roster ({len(filtered_df)} Matching Records)")

# Format layout table for easy user consumption
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


# ── 5. ITEMIZATIONS & DEEP DIVE (THE ZIP ALIGNMENT PATTERN) ──────────
st.subheader("Inmate Profile Deep-Dive")
st.markdown("Select a specific row record below to untangle and audit their exact charges and statute assignments.")

# Generate distinct selectable dropdown options for every inmate matching the filter
inmate_options = []
for idx, row in filtered_df.iterrows():
    primary_charge = row['charges_str'].split(';')[0].strip()
    label = f"{row['booking_date']} | {primary_charge} ({row['charge_level']})"
    inmate_options.append((idx, label))

if inmate_options:
    selected_idx = st.selectbox(
        "Select an inmate profile to extract:", 
        options=[opt[0] for opt in inmate_options],
        format_func=lambda x: next(opt[1] for opt in inmate_options if opt[0] == x)
    )
    
    inmate_data = filtered_df.loc[selected_idx]
    
    # Split strings by semicolon. Keep empty statutes intact to guarantee index tracking.
    raw_charges = [c.strip() for c in inmate_data['charges_str'].split(';') if c.strip()]
    raw_statutes = [s.strip() for s in inmate_data['statute_codes'].split(';')]
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### Aligned Rap Sheet")
        for i, charge in enumerate(raw_charges):
            # Guard against potential structural array size mismatches out of the CSV
            statute_code = "None Listed/Found"
            if i < len(raw_statutes) and raw_statutes[i]:
                statute_code = raw_statutes[i]
                
            # Render visually as distinct structural sections rather than ugly raw text
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

