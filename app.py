import streamlit as st
import pandas as pd
import os
import glob

st.set_page_config(page_title="Dane County Jail Roster Dashboard", layout="wide")

# ── 1. LOAD DATA VIA LOCAL WORKSPACE (STREAMLIT CLONE) ────────────────
@st.cache_data(ttl=600)  # Caches data for 10 minutes to keep the app lightning fast
def load_data():
    # Find all CSV files in the folder
    all_csvs = glob.glob("dane_jail_*.csv")
    
    # Strictly isolate the daily files by ignoring the full_scrape master file
    timestamped_files = [f for f in all_csvs if "full_scrape" not in f]
    
    if not timestamped_files:
        # Fallback to full scrape if no daily files are present
        if os.path.exists("dane_jail_full_scrape.csv"):
            latest_file = "dane_jail_full_scrape.csv"
        else:
            return pd.DataFrame(), "No files found"
    else:
        # Grab the absolute newest daily file based on file modification time
        latest_file = max(timestamped_files, key=os.path.getmtime)
    
    df = pd.read_csv(latest_file)
    
    # Defensive cleanup: Convert NaN values to safe defaults so string splits never crash
    df['charges_str'] = df['charges_str'].fillna("")
    df['statute_codes'] = df['statute_codes'].fillna("")
    df['arrest_agencies'] = df['arrest_agencies'].fillna("Unknown Agency")
    df['charge_level'] = df['charge_level'].fillna("Unknown")
    df['total_charge_counts'] = df['total_charge_counts'].fillna(0).astype(int)
    df['booking_date'] = df['booking_date'].fillna("Unknown Date")
    
    return df, latest_file

# Execute data load
df, file_source = load_data()

if df.empty:
    st.error("No data files found in the repository workspace. Please run your scraper first.")
    st.stop()


# ── 2. HEADER & KPI METRICS ──────────────────────────────────────────
st.title("Dane County Jail Roster Analysis")
st.caption(f"Active Workspace File: `{file_source}`")

# Calculate metrics safely
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


# ── 3. SIDEBAR FILTERS ───────────────────────────────────────────────
st.sidebar.header("Filter Options")

# Text search through charge descriptions
search_query = st.sidebar.text_input("Search Charge Descriptions", "").strip().upper()

# Severity Dropdown
severity_options = ["All"] + sorted(list(df['charge_level'].unique()))
selected_severity = st.sidebar.selectbox("Filter by Severity Level", severity_options)

# Agency Dropdown (Splits multi-agency strings into clean, single filter options)
unique_agencies = set()
for agency_str in df['arrest_agencies'].unique():
    for a in agency_str.split(";"):
        if a.strip() and a.strip() != "Unknown Agency":
            unique_agencies.add(a.strip())
agency_options = ["All"] + sorted(list(unique_agencies))
selected_agency = st.sidebar.selectbox("Filter by Arresting Agency", agency_options)

# Apply filter configurations
filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['charges_str'].str.contains(search_query, na=False)]

if selected_severity != "All":
    filtered_df = filtered_df[filtered_df['charge_level'] == selected_severity]

if selected_agency != "All":
    filtered_df = filtered_df[filtered_df['arrest_agencies'].str.contains(selected_agency, na=False)]


# ── 4. MAIN ROSTER TABLE ─────────────────────────────────────────────
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


# ── 5. DEEP DIVE VIEW (ZIP ALIGNMENT) ────────────────────────────────
st.subheader("Inmate Profile Deep-Dive")

# Map inmates to a dictionary to prevent format-selection indexing errors
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
    
    # Split strings apart safely
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


