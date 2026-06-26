import streamlit as st
import pandas as pd
import os
import glob

st.set_page_config(page_title="Dane County Jail Roster Dashboard", layout="wide")

# ── 1. LOAD DATA SAFELY ──────────────────────────────────────────────
@st.cache_data(ttl=600)  # Caches data for 10 minutes to keep app fast
def load_data():
    # Find the most recent daily CSV file in the directory
    csv_files = glob.glob("dane_jail_*.csv")
    if not csv_files:
        # Fallback to full scrape if daily isn't found
        if os.path.exists("dane_jail_full_scrape.csv"):
            csv_files = ["dane_jail_full_scrape.csv"]
        else:
            return pd.DataFrame() # Return empty if no files exist

    latest_file = max(csv_files, key=os.path.getmtime)
    
    df = pd.read_csv(latest_file)
    
    # Fill NaN values defensively so string operations don't break
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

# ── 2. HEADER & METRICS ──────────────────────────────────────────────
st.title("Dane County Jail Roster Analysis")
st.caption(f"Displaying records from: **{file_source}**")

# Calculate high level metrics
total_inmates = len(df)
felonies = len(df[df['charge_level'] == 'Felony'])
misdemeanors = len(df[df['charge_level'] == 'Misdemeanor'])
unknowns = len(df[df['charge_level'] == 'Unknown'])

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Inmates", total_inmates)
m2.metric("Felony Holds", felonies, delta_color="inverse")
m3.metric("Misdemeanors", misdemeanors)
m4.metric("Unmapped/Unknown", unknowns)

st.markdown("---")

# ── 3. SIDEBAR FILTERS ──────────────────────────────────────────────
st.sidebar.header("Filter & Search Options")

# Search Input
search_query = st.sidebar.text_input("Search by Charge Description", "").strip().upper()

# Severity Filter
severity_options = ["All"] + list(df['charge_level'].unique())
selected_severity = st.sidebar.selectbox("Filter by Severity Level", severity_options)

# Agency Filter
# Extract all unique individual agencies across the semicolon strings
unique_agencies = set()
for agency_str in df['arrest_agencies'].unique():
    for a in agency_str.split(";"):
        if a.strip():
            unique_agencies.add(a.strip())
agency_options = ["All"] + sorted(list(unique_agencies))
selected_agency = st.sidebar.selectbox("Filter by Arresting Agency", agency_options)

# Apply Filter Logic
filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['charges_str'].str.contains(search_query, na=False)]

if selected_severity != "All":
    filtered_df = filtered_df[filtered_df['charge_level'] == selected_severity]

if selected_agency != "All":
    filtered_df = filtered_df[filtered_df['arrest_agencies'].str.contains(selected_agency, na=False)]


# ── 4. ROSTER ROSTERS DISPLAY ────────────────────────────────────────
st.subheader(f"Current Bookings ({len(filtered_df)} matches found)")

# Display a clean, aggregated layout table
display_cols = ['booking_date', 'charge_level', 'total_charge_counts', 'arrest_agencies']
st.dataframe(
    filtered_df[display_cols].rename(columns={
        'booking_date': 'Booking Date',
        'charge_level': 'Severity',
        'total_charge_counts': 'Total Charges',
        'arrest_agencies': 'Arresting Agency'
    }),
    use_container_width=True
)

st.markdown("---")

# ── 5. DEEP DIVE / DETAILS VIEW ──────────────────────────────────────
st.subheader("Inmate Charge Deep-Dive")
st.info("Select an inmate below to view their fully aligned rap sheet and statute citations.")

# Select box to pick an inmate via row selection
inmate_options = []
for idx, row in filtered_df.iterrows():
    # Show main charge snippet as label
    primary_charge = row['charges_str'].split(';')[0]
    inmate_options.append((idx, f"{row['booking_date']} - {primary_charge} ({row['charge_level']})"))

if inmate_options:
    selected_idx = st.selectbox(
        "Choose an inmate record to inspect:", 
        options=[opt[0] for opt in inmate_options],
        format_func=lambda x: next(opt[1] for opt in inmate_options if opt[0] == x)
    )
    
    inmate_data = filtered_df.loc[selected_idx]
    
    # Realign charges and statutes safely using Zip logic
    raw_charges = [c.strip() for c in inmate_data['charges_str'].split(';') if c.strip()]
    raw_statutes = [s.strip() for s in inmate_data['statute_codes'].split(';')]
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### Itemized Charges & Statutes")
        for i, charge in enumerate(raw_charges):
            # Fallback safely if statutes array is shorter than charges array
            statute_code = "None Listed"
            if i < len(raw_statutes) and raw_statutes[i]:
                statute_code = raw_statutes[i]
                
            st.markdown(f"**{i+1}. {charge}**")
            st.caption(f"Statute Citation: `{statute_code}`")
            
    with col2:
        st.markdown("#### Booking Metadata")
        st.write(f"**Booking Time:** {inmate_data['booking_date']}")
        st.write(f"**Primary Severity:** {inmate_data['charge_level']}")
        st.write(f"**Arresting Agencies:** {inmate_data['arrest_agencies']}")
        st.write(f"**Total Counts:** {inmate_data['total_charge_counts']}")
        st.markdown(f"[🔗 View Original Sheriff Record]({inmate_data['url']})")
else:
    st.warning("No records match the active filter selections.")
