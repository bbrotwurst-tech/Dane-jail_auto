import streamlit as st
import pandas as pd

st.set_page_config(page_title="Dane County Jail Roster", layout="wide")

st.title("Dane County Jail Data")

# Load the file directly from your repo
@st.cache_data
def load_data():
    df = pd.read_csv("dane_jail_full_scrape.csv")
    return df

df = load_data()

# Create a filter
level = st.multiselect("Filter by Charge Level", df['charge_level'].unique())

if level:
    df = df[df['charge_level'].isin(level)]

# Show the data
st.dataframe(df, use_container_width=True)

