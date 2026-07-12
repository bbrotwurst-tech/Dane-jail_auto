"""
Trends in jail population by physical location/building over time,
built from the full history of merged_jail_data_YYYY-MM-DD.csv files.

Usage in your main app:
    from location_trends import render_location_trends
    render_location_trends("merged")  # path to folder of merged_jail_data_*.csv files
"""

import glob
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _load_location_history(merged_dir: str) -> pd.DataFrame:
    """Build a date x location count table from all merged files in the folder."""
    files = sorted(glob.glob(os.path.join(merged_dir, "merged_jail_data_*.csv")))

    rows = []
    for f in files:
        df = pd.read_csv(f)
        if "Location" not in df.columns or "Minute of Timestamp" not in df.columns:
            continue

        # Filename date is more reliable for sorting than the free-text timestamp field
        fname = os.path.basename(f)
        date_str = fname.replace("merged_jail_data_", "").replace(".csv", "")

        counts = df["Location"].value_counts()
        for loc, count in counts.items():
            rows.append({"date": date_str, "location": loc, "count": count})

    if not rows:
        return pd.DataFrame()

    history = pd.DataFrame(rows)
    history["date"] = pd.to_datetime(history["date"])
    return history.sort_values("date")


def render_location_trends(merged_dir: str = "merged"):
    """Render a line chart of population by location, trended over all available days."""
    history = _load_location_history(merged_dir)

    if history.empty:
        st.warning("No historical merged data found to build location trends.")
        return

    pivot = history.pivot(index="date", columns="location", values="count").fillna(0)

    all_locations = pivot.columns.tolist()
    default_selection = [loc for loc in ["Public Safety Building", "City-County Building"] if loc in all_locations] or all_locations

    selected = st.multiselect(
        "Select locations to plot:",
        options=all_locations,
        default=default_selection,
    )

    if not selected:
        st.info("Select at least one location to display.")
        return

    fig = go.Figure()
    for loc in selected:
        fig.add_trace(go.Scatter(
            x=pivot.index,
            y=pivot[loc],
            mode="lines+markers",
            name=loc,
        ))

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Residents",
        height=400,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    st.plotly_chart(fig, use_container_width=True)
