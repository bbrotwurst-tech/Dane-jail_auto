import streamlit as st
import pandas as pd
import glob
import plotly.express as px

# ── 1. Page Configuration ──────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Dane Jail Analytics")

st.title("📊 Dane County Jail Trend Analysis")

# ── 2. Data Loader (Robust) ────────────────────────────────────────────────
@st.cache_data
def load_all_data():
    files = glob.glob("dane_jail_*.csv")
    all_data = []
    
    for file in files:
        # Ignore the master file to prevent date parsing errors
        if "full_scrape" in file:
            continue
            
        try:
            # Extract date from filename (e.g., 'dane_jail_2026-06-25.csv' -> '2026-06-25')
            date_str = file.split('_')[-1].replace('.csv', '')
            
            # Read and process
            df = pd.read_csv(file)
            df['date'] = pd.to_datetime(date_str)
            all_data.append(df)
        except Exception as e:
            st.warning(f"Skipping corrupt file {file}: {e}")
    
    if not all_data:
        return pd.DataFrame()
        
    return pd.concat(all_data)

# ── 3. Processing and Aggregation ────────────────────────────────────────
