import streamlit as st
import pandas as pd
import glob
import plotly.express as px
import os

# --- 1. Page Configuration & Style ---
st.set_page_config(layout="wide", page_title="Dane County Jail Analytics")

st.title("📊 Dane County Jail: Historical Archive")
st.markdown("Automated pipeline tracking daily population and charge trends.")

# --- 2. Robust Data Ingestion ---
@st.cache_data
def load_all_data():
    """Loads all timestamped CSVs, filtering out master files."""
    files = glob.glob("dane_jail_20*.csv")
    all_data = []
    
    for file in files:
        if "full_scrape" in file:
            continue
            
        try:
            # Extract date from filename: 'dane_jail_YYYY-MM-DD.csv'
            date_str = file.split('_')[-1].replace('.csv', '')
            df = pd.read_csv(file)
            df['date'] = pd.to_datetime(date_str)
            all_data.append(df)
        except Exception as e:
            continue # Silently skip malformed files
            
    return pd.concat(all_data) if all_data else pd.DataFrame()

# Load the data
df = load_all_data()

# --- 3. Dashboard Logic ---
if df.empty:
    st.warning("No data files detected. Pipeline is running, please check back later.")
else:
    # Sidebar Filters
    st.sidebar.header("Filters")
    selected_level = st.sidebar.multiselect("Select Charge Level", df['charge_level'].unique())
    
    filtered_df = df.copy()
    if selected_level:
        filtered_df = filtered_df[filtered_df['charge_level'].isin(selected_level)]

    # Top-Level Metrics (KPIs)
    latest_date = filtered_df['date'].max().strftime('%Y-%m-%d')
    latest_data = filtered_df[filtered_df['date'] == filtered_df['date'].max()]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Inmates (Latest)", len(latest_data))
    col2.metric("Felony Count", len(latest_data[latest_data['charge_level'] == 'Felony']))
    col3.metric("Data Points Collected", len(df))

    # Visualization Section
    st.divider()
    
    # Process for Time-Series
    daily_trends = filtered_df.groupby(['date', 'charge_level']).size().unstack(fill_value=0)
    daily_trends = daily_trends.sort_index()

    if len(daily_trends) >= 7:
        st.subheader("7-Day Rolling Average")
        rolling_avg = daily_trends.rolling(window=7).mean()
        fig = px.line(rolling_avg, title="Trends over time (Rolling Avg)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.subheader("Population by Charge Level")
        st.bar_chart(daily_trends)
        st.info(f"Collecting data... {7 - len(daily_trends)} more days needed for rolling trend analysis.")

    # Data Explorer
    with st.expander("View Raw Archive Data"):
        st.dataframe(df.sort_values(by='date', ascending=False), use_container_width=True)
