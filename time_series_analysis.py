"""
Dane County Time Series Analysis
──────────────────────────────────
Extends the existing historical trend infrastructure in app.py
(process_historical_trends, compute_turnover) with deeper time-series
views: rolling averages, day-of-week booking patterns, charge-mix
drift over time, stay-length trends, and agency activity over time.

Designed to be imported into app.py and called as an additional
section after the existing "Population Trends Over Time" section.
"""

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime


# ── 1. ROLLING AVERAGE POPULATION TRENDS ────────────────────────────
def add_rolling_averages(trend_df, window=7):
    """Adds N-day rolling average columns to smooth day-to-day noise
    in the existing population trend data."""
    trend_df = trend_df.copy()
    trend_df["Date"] = pd.to_datetime(trend_df["Date"])
    trend_df = trend_df.sort_values("Date")

    for col in ["Total Population", "Felony Holds", "Misdemeanors", "Civil / Traffic"]:
        if col in trend_df.columns:
            trend_df[f"{col} ({window}d avg)"] = (
                trend_df[col].rolling(window=window, min_periods=1).mean()
            )
    return trend_df


def render_rolling_trends(trend_df, window=7):
    st.subheader(f"Population Trends — Raw vs. {window}-Day Rolling Average")
    st.caption(
        "Raw daily counts are noisy (weekend booking spikes, single-day "
        "anomalies). The rolling average smooths this out to show the "
        "underlying trend more clearly."
    )

    smoothed = add_rolling_averages(trend_df, window=window)

    metric = st.selectbox(
        "Metric to smooth:",
        ["Total Population", "Felony Holds", "Misdemeanors", "Civil / Traffic"],
        key="rolling_metric_select",
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=smoothed["Date"], y=smoothed[metric],
        mode="lines", name="Raw daily value",
        line=dict(color="lightgray", width=1),
    ))
    fig.add_trace(go.Scatter(
        x=smoothed["Date"], y=smoothed[f"{metric} ({window}d avg)"],
        mode="lines", name=f"{window}-day rolling avg",
        line=dict(color="dodgerblue", width=3),
    ))
    fig.update_layout(
        xaxis_title="Date", yaxis_title=metric,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


# ── 2. BOOKING/EXIT VELOCITY BY DAY OF WEEK ──────────────────────────
def compute_day_of_week_turnover(turnover_df):
    """Takes the existing turnover_df (from compute_turnover in app.py)
    and breaks average bookings/exits down by day of week, using the
    later date in each 'X -> Y' transition string as the reference day."""
    if turnover_df.empty:
        return pd.DataFrame()

    df = turnover_df.copy()
    # Transition strings look like "2026-06-25 -> 2026-06-26"; the
    # second date is the day the booking activity is attributed to.
    df["ref_date"] = df["Transition"].str.split(" -> ").str[1]
    df["ref_date"] = pd.to_datetime(df["ref_date"], errors="coerce")
    df = df.dropna(subset=["ref_date"])
    df["day_of_week"] = df["ref_date"].dt.day_name()

    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    grouped = df.groupby("day_of_week")[["Booked", "Exited"]].mean().reindex(day_order)
    grouped = grouped.reset_index()
    return grouped


def render_day_of_week_analysis(turnover_df):
    st.subheader("Booking Activity by Day of Week")
    st.caption(
        "Average bookings/exits per day of week, across all data collected so far. "
        "More days of history = more reliable pattern (a single week of data can "
        "look noisy)."
    )

    dow_df = compute_day_of_week_turnover(turnover_df)
    if dow_df.empty or dow_df["Booked"].isna().all():
        st.info("Not enough turnover history yet to break this down by day of week.")
        return

    fig = px.bar(
        dow_df, x="day_of_week", y=["Booked", "Exited"],
        barmode="group",
        labels={"day_of_week": "Day of Week", "value": "Average Count", "variable": "Type"},
    )
    st.plotly_chart(fig, use_container_width=True)


# ── 3. CHARGE-LEVEL MIX DRIFT OVER TIME ──────────────────────────────
def compute_charge_mix_over_time(timestamped_files, extract_date_fn):
    """Recomputes the Felony/Misdemeanor/Civil/Unknown proportion (not
    just raw count) for each day, so you can see whether the *severity
    mix* of the population is shifting over time, independent of total
    population size."""
    records = []
    for f in timestamped_files:
        date_str = extract_date_fn(f)
        if date_str is None:
            continue
        try:
            day_df = pd.read_csv(f)
        except Exception:
            continue
        total = len(day_df)
        if total == 0 or "charge_level" not in day_df.columns:
            continue
        vc = day_df["charge_level"].value_counts()
        records.append({
            "Date": date_str,
            "Felony %": 100 * vc.get("Felony", 0) / total,
            "Misdemeanor %": 100 * vc.get("Misdemeanor", 0) / total,
            "Civil %": 100 * vc.get("Civil", 0) / total,
            "Unknown %": 100 * vc.get("Unknown", 0) / total,
        })
    if not records:
        return pd.DataFrame()
    out = pd.DataFrame(records).sort_values("Date")
    out["Date"] = pd.to_datetime(out["Date"])
    return out


def render_charge_mix_trend(timestamped_files, extract_date_fn):
    st.subheader("Charge Severity Mix Over Time")
    st.caption(
        "Shows what % of the jail population falls into each severity tier "
        "on each day -- separate from total population size, so you can see "
        "if the *composition* is shifting even when the headcount is stable."
    )

    mix_df = compute_charge_mix_over_time(timestamped_files, extract_date_fn)
    if mix_df.empty or len(mix_df) < 2:
        st.info("Need at least two days of data to show a mix trend.")
        return

    fig = px.area(
        mix_df, x="Date", y=["Felony %", "Misdemeanor %", "Civil %", "Unknown %"],
        labels={"value": "% of Population", "variable": "Severity"},
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)


# ── 4. STAY LENGTH TREND OVER TIME ───────────────────────────────────
def compute_stay_length_trend(timestamped_files, extract_date_fn, compute_stay_length_fn):
    """Recomputes median/mean stay length for each historical day's
    snapshot, so you can see whether people are being held longer or
    shorter over time, not just as of the latest snapshot."""
    records = []
    for f in timestamped_files:
        date_str = extract_date_fn(f)
        if date_str is None:
            continue
        try:
            day_df = pd.read_csv(f)
        except Exception:
            continue
        if "booking_date" not in day_df.columns:
            continue
        _, days_held = compute_stay_length_fn(day_df, date_str)
        if days_held.empty:
            continue
        records.append({
            "Date": date_str,
            "Median Stay (d)": days_held.median(),
            "Mean Stay (d)": days_held.mean(),
        })
    if not records:
        return pd.DataFrame()
    out = pd.DataFrame(records).sort_values("Date")
    out["Date"] = pd.to_datetime(out["Date"])
    return out


def render_stay_length_trend(timestamped_files, extract_date_fn, compute_stay_length_fn):
    st.subheader("Length of Stay Trend Over Time")
    st.caption(
        "Median and mean days held, computed fresh for each historical "
        "snapshot -- shows whether people are generally being held longer "
        "or shorter as the dataset grows, not just a single current figure."
    )

    stay_trend_df = compute_stay_length_trend(timestamped_files, extract_date_fn, compute_stay_length_fn)
    if stay_trend_df.empty or len(stay_trend_df) < 2:
        st.info("Need at least two days of data with valid booking dates to show this trend.")
        return

    fig = px.line(
        stay_trend_df, x="Date", y=["Median Stay (d)", "Mean Stay (d)"],
        markers=True,
        labels={"value": "Days Held", "variable": "Metric"},
    )
    st.plotly_chart(fig, use_container_width=True)


# ── 5. AGENCY ACTIVITY OVER TIME ─────────────────────────────────────
def compute_agency_activity_over_time(timestamped_files, extract_date_fn, top_n_agencies=5):
    """Tracks how many inmates each of the top N most active agencies
    are associated with, per day -- lets you see if a particular
    agency's activity is trending up or down."""
    daily_agency_counts = {}
    all_agency_totals = {}

    for f in timestamped_files:
        date_str = extract_date_fn(f)
        if date_str is None:
            continue
        try:
            day_df = pd.read_csv(f)
        except Exception:
            continue
        if "arrest_agencies" not in day_df.columns:
            continue

        day_counts = {}
        for agency_str in day_df["arrest_agencies"].dropna():
            for a in str(agency_str).split(";"):
                a = a.strip()
                if a and a != "Unknown Agency":
                    day_counts[a] = day_counts.get(a, 0) + 1
                    all_agency_totals[a] = all_agency_totals.get(a, 0) + 1

        daily_agency_counts[date_str] = day_counts

    if not all_agency_totals:
        return pd.DataFrame()

    top_agencies = sorted(all_agency_totals, key=all_agency_totals.get, reverse=True)[:top_n_agencies]

    records = []
    for date_str, day_counts in daily_agency_counts.items():
        row = {"Date": date_str}
        for agency in top_agencies:
            row[agency] = day_counts.get(agency, 0)
        records.append(row)

    out = pd.DataFrame(records).sort_values("Date")
    out["Date"] = pd.to_datetime(out["Date"])
    return out, top_agencies


def render_agency_activity_trend(timestamped_files, extract_date_fn, top_n_agencies=5):
    st.subheader("Agency Activity Over Time")
    st.caption(
        f"Daily inmate counts associated with the top {top_n_agencies} most "
        "active arresting agencies (by total historical volume)."
    )

    result = compute_agency_activity_over_time(timestamped_files, extract_date_fn, top_n_agencies)
    if not result or result[0].empty or len(result[0]) < 2:
        st.info("Need at least two days of data to show agency activity trends.")
        return

    activity_df, top_agencies = result
    fig = px.line(
        activity_df, x="Date", y=top_agencies, markers=True,
        labels={"value": "Inmates", "variable": "Agency"},
    )
    st.plotly_chart(fig, use_container_width=True)


# ── ORCHESTRATOR: render all sections at once ────────────────────────
def render_time_series_section(trend_df, turnover_df, timestamped_files,
                                 extract_date_fn, compute_stay_length_fn):
    """Call this from app.py to render the full time-series analysis
    block in one go. Example usage in app.py, after the existing
    'Population Trends Over Time' section:

        from time_series_analysis import render_time_series_section
        render_time_series_section(
            trend_df, turnover_df, historical_file_list,
            extract_date, compute_stay_length
        )
    """
    st.markdown("---")
    st.header("📈 Time Series Analysis")

    if trend_df.empty or len(trend_df) < 2:
        st.info("Time series analysis requires at least two days of historical data.")
        return

    render_rolling_trends(trend_df, window=7)
    st.markdown("---")
    render_day_of_week_analysis(turnover_df)
    st.markdown("---")
    render_charge_mix_trend(timestamped_files, extract_date_fn)
    st.markdown("---")
    render_stay_length_trend(timestamped_files, extract_date_fn, compute_stay_length_fn)
    st.markdown("---")
    render_agency_activity_trend(timestamped_files, extract_date_fn)
