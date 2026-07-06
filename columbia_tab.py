import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# ── Load data ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600)  # refresh cache hourly so new weekly commits show up
def load_columbia_data():
    df = pd.read_csv("columbia_bookings_log.csv")

    # booking_datetime looks like "14:27:14 06/22/26" -- parse into real datetime
    df["booking_dt"] = pd.to_datetime(
        df["booking_datetime"], format="%H:%M:%S %m/%d/%y", errors="coerce"
    )
    df["booking_date"] = df["booking_dt"].dt.date
    df["booking_week"] = df["booking_dt"].dt.to_period("W").apply(lambda p: p.start_time)

    return df


def render_columbia_tab():
    st.header("Columbia County Bookings")
    st.caption(
        "Sourced from the Columbia County Sheriff's weekly Booking Summary Report. "
        "This is a **bookings log**, not a live custody roster — it shows who was "
        "booked in, not who is currently in jail or when they were released."
    )

    df = load_columbia_data()

    if df.empty:
        st.warning("No booking data available yet.")
        return

    # ── Top-line metrics ──────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Bookings Logged", len(df))
    col2.metric("Unique Individuals", df["name_number"].nunique())
    col3.metric(
        "Most Recent Booking",
        df["booking_dt"].max().strftime("%m/%d/%y") if df["booking_dt"].notna().any() else "N/A",
    )

    st.divider()

    # ── Bookings over time ─────────────────────────────────────────
    st.subheader("Bookings per Week")
    weekly_counts = df.groupby("booking_week").size().reset_index(name="bookings")
    fig_weekly = px.line(
        weekly_counts, x="booking_week", y="bookings", markers=True,
        labels={"booking_week": "Week", "bookings": "Number of Bookings"},
    )
    st.plotly_chart(fig_weekly, use_container_width=True)

    # ── Booking type breakdown ──────────────────────────────────────
    st.subheader("Booking Type Breakdown")
    booking_type_counts = df["booking_type"].value_counts().reset_index()
    booking_type_counts.columns = ["booking_type", "count"]
    fig_types = px.bar(
        booking_type_counts.head(10), x="count", y="booking_type", orientation="h",
        labels={"count": "Number of Bookings", "booking_type": "Booking Type"},
    )
    fig_types.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig_types, use_container_width=True)

    # ── Most common charges ─────────────────────────────────────────
    st.subheader("Most Common Charges")
    all_offenses = df["offenses"].dropna().str.split("; ").explode()
    top_offenses = all_offenses.value_counts().head(15).reset_index()
    top_offenses.columns = ["offense", "count"]
    fig_offenses = px.bar(
        top_offenses, x="count", y="offense", orientation="h",
        labels={"count": "Number of Charges", "offense": "Offense"},
    )
    fig_offenses.update_layout(yaxis={"categoryorder": "total ascending"}, height=500)
    st.plotly_chart(fig_offenses, use_container_width=True)

    st.divider()

    # ── Raw searchable table ────────────────────────────────────────
    # Names intentionally excluded to match Dane County tab's privacy posture.
    # name_number is kept so repeat bookings of the same person are still
    # visible without exposing an actual name.
    st.subheader("Full Bookings Log")
    search = st.text_input("Search by charge or address", "")
    display_df = df[
        ["name_number", "age", "address", "booking_dt", "booking_type", "offenses"]
    ].sort_values("booking_dt", ascending=False)

    if search:
        mask = (
            display_df["offenses"].str.contains(search, case=False, na=False)
            | display_df["address"].str.contains(search, case=False, na=False)
        )
        display_df = display_df[mask]

    st.dataframe(display_df, use_container_width=True, hide_index=True)


# ── Example of how to wire this into your existing app.py ──────────
# In your main streamlit_app.py:
#
#   from columbia_tab import render_columbia_tab
#
#   tab_dane, tab_columbia = st.tabs(["Dane County", "Columbia County"])
#
#   with tab_dane:
#       render_dane_tab()   # your existing Dane dashboard code
#
#   with tab_columbia:
#       render_columbia_tab()

if __name__ == "__main__":
    st.set_page_config(page_title="Columbia County Bookings", layout="wide")
    render_columbia_tab()
