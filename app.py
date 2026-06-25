import streamlit as st
import pandas as pd
import glob
import os

st.set_page_config(page_title="Jail History Explorer", layout="wide")
st.title("Dane County Jail: Historical Archive")

# 1. Find all files that start with 'dane_jail_' and look like a date (YYYY-MM-DD)
# This ignores the 'dane_jail_full_scrape.csv' file
files = sorted(glob.glob("dane_jail_20*.csv"), reverse=True)

if not files:
    st.error("No historical files found!")
else:
    # 2. Create a dropdown to select the date
    selected_file = st.selectbox("Select a date to view:", files)

    # 3. Load the data
    @st.cache_data
    def load_data(file_path):
        return pd.read_csv(file_path)

    df = load_data(selected_file)

    st.write(f"Showing data from: **{selected_file}**")

    # 4. Filters and Display
    level = st.multiselect("Filter by Charge Level", df['charge_level'].unique())
    if level:
        df = df[df['charge_level'].isin(level)]

    st.dataframe(df, use_container_width=True)

