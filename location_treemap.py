"""
Treemap view of Dane County jail population by building and housing unit
(e.g., Public Safety Building > P4K, City-County Building > 7WEST).

A treemap fits this better than a literal map, since housing units like
7WEST or P4A are floors/pods inside a building, not separate street
addresses with their own coordinates.

Usage in your main app:
    from location_treemap import render_location_treemap
    render_location_treemap(latest_df)
"""

import pandas as pd
import plotly.express as px
import streamlit as st


def render_location_treemap(df: pd.DataFrame):
    """Render a treemap of population by building (Location) and unit (Level2)."""
    required_cols = {"Location", "Level2"}
    if not required_cols.issubset(df.columns):
        st.warning(f"Data is missing required columns: {required_cols - set(df.columns)}")
        return

    counts = (
        df.groupby(["Location", "Level2"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    if counts.empty:
        st.warning("No location/unit data found.")
        return

    fig = px.treemap(
        counts,
        path=["Location", "Level2"],
        values="count",
        color="Location",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )

    fig.update_traces(
        textinfo="label+value",
        textfont=dict(size=13),
        marker=dict(line=dict(width=1, color="white")),
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=500,
    )

    st.plotly_chart(fig, use_container_width=True)

    total = counts["count"].sum()
    st.caption(f"Total residents shown: {total}")
