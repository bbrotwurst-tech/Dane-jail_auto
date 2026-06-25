import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(layout="wide", page_title="Jail Analytics")

# 1. Header and Sidebar
st.title("📊 Dane County Jail Dashboard")
st.sidebar.header("Filters")

# Load data (Assuming you have a function for this)
df = load_data() 

# Sidebar Filters
levels = st.sidebar.multiselect("Charge Level", df['charge_level'].unique())
if levels:
    df = df[df['charge_level'].isin(levels)]

# 2. Top-level KPIs (The "Eye-Catching" part)
col1, col2, col3 = st.columns(3)
col1.metric("Total Inmates", len(df))
col2.metric("Felony Count", len(df[df['charge_level'] == 'Felony']))
col3.metric("Avg Counts per Inmate", round(df['total_charge_counts'].mean(), 1))

# 3. Visualization
st.subheader("Charges by Category")
chart_data = df['charge_level'].value_counts().reset_index()
fig = px.bar(chart_data, x='charge_level', y='count', color='charge_level')
st.plotly_chart(fig, use_container_width=True)

# 4. Data Table
with st.expander("View Raw Data"):
    st.dataframe(df, use_container_width=True)
