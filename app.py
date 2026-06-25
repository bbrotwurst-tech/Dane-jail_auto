import streamlit as st
import pandas as pd
import glob
import plotly.express as px
import os

st.set_page_config(layout="wide", page_title="Debug Dashboard")
st.title("📊 Debug Dashboard")

# 1. Debug: Check where the app is looking
st.write(f"Current Working Directory: {os.getcwd()}")
files = glob.glob("dane_jail_*.csv")
st.write("Files detected by glob:", files)

@st.cache_data
def load_all_data():
    all_data = []
    for file in files:
        if "full_scrape" in file: continue
        try:
            date_str = file.split('_')[-1].replace('.csv', '')
            df = pd.read_csv(file)
            df['date'] = pd.to_datetime(date_str)
            all_data.append(df)
        except Exception as e:
            st.warning(f"Error reading {file}: {e}")
    return pd.concat(all_data) if all_data else pd.DataFrame()

df = load_all_data()

if df.empty:
    st.error("No data found! Check that CSVs are in the same folder as app.py.")
else:
    st.success(f"Loaded {len(df)} total rows of data.")
    
    # Process for plotting
    daily_trends = df.groupby(['date', 'charge_level']).size().unstack(fill_value=0)
    daily_trends = daily_trends.sort_index()

    # --- THE FIX ---
    # If we have less than 7 days, rolling(7) is empty. 
    # Let's show raw data if we don't have enough history yet.
    if len(daily_trends) < 7:
        st.warning("Not enough data yet for a 7-day average. Showing raw counts:")
        st.line_chart(daily_trends)
    else:
        rolling_avg = daily_trends.rolling(window=7).mean()
        fig = px.line(rolling_avg, title="7-Day Rolling Avg")
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("View Raw Data"):
        st.dataframe(df)
