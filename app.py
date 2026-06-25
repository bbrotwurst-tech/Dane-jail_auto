import streamlit as st
import pandas as pd
import glob
import plotly.express as px

st.set_page_config(layout="wide", page_title="Jail Trend Analytics")

@st.cache_data
def load_all_data():
    files = glob.glob("dane_jail_*.csv") # Adjust path if using a /data folder
    all_data = []
    
    for file in files:
        # Extract date from filename (e.g., 'dane_jail_2026-06-25.csv' -> '2026-06-25')
        date_str = file.split('_')[-1].replace('.csv', '')
        df = pd.read_csv(file)
        df['date'] = pd.to_datetime(date_str)
        all_data.append(df)
    
    return pd.concat(all_data)

# 1. Load and prepare
df = load_all_data()

# 2. Reshape the data for plotting
# Count occurrences of each 'charge_level' per day
daily_trends = df.groupby(['date', 'charge_level']).size().unstack(fill_value=0)

# 3. Calculate 7-day Rolling Average
rolling_avg = daily_trends.rolling(window=7).mean()

# 4. Displaying the graph
st.title("Trend Analysis: 7-Day Rolling Average")

# Plotting using Plotly
fig = px.line(rolling_avg, title="Jail Population by Charge Level (7-Day Rolling Avg)")
st.plotly_chart(fig, use_container_width=True)

# 5. Raw Data Preview
with st.expander("Show Daily Aggregated Data"):
    st.write(rolling_avg)

