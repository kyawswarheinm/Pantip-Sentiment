"""Pantip SET Sentiment Monitor — Streamlit dashboard."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.components.alert_banner import render_alert_banner
from dashboard.components.documentation import render_documentation_tab
from dashboard.components.posts_feed import render_posts_feed
from dashboard.components.sentiment_chart import render_sentiment_chart
from dashboard.components.sentiment_ranking import render_sentiment_ranking, render_volume_chart
from dashboard.utils import (
    load_active_tickers,
    load_alerts,
    load_prices,
    load_recent_posts,
    load_sentiment_rankings,
    load_sentiment_timeseries,
    load_summary_metrics,
    load_tickers,
    load_volume_timeseries,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SET Sentiment Monitor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Design tokens injected as CSS variables + component overrides
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --bg:        #080e1d;
  --surface:   #0d1526;
  --surface2:  #172a48;
  --border:    #1e3050;
  --border2:   #2b4368;
  --text:      #e8edf5;
  --muted:     #e2e8f0;
  --subtle:    #334155;
  --accent:    #3b82f6;
  --green:     #22c55e;
  --red:       #ef4444;
  --amber:     #f59e0b;
}

/* Base */
html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 1px 1px, #091a40 1px, transparent 0) 0 0 / 25px 25px,
    var(--bg) !important;
  font-family: Inter, system-ui, -apple-system, sans-serif;
  color: var(--text);
}

/* Main container */
.main .block-container {
  padding: 1.5rem 2rem 3rem;
  max-width: 1440px;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] .block-container {
  padding: 1.5rem 1.25rem;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--border2);
  border-radius: 6px;
  border: 2px solid var(--bg);
}
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* ── Metric cards ── */
[data-testid="metric-container"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1rem 1.25rem !important;
  box-shadow: 0 1px 2px rgba(0,0,0,0.25);
  transition: border-color 150ms ease, transform 150ms ease, box-shadow 150ms ease;
}
[data-testid="metric-container"]:hover {
  border-color: var(--border2);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(0,0,0,0.35);
}
[data-testid="metric-container"] label {
  color: var(--muted) !important;
  font-size: 0.7rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
[data-testid="stMetricValue"] {
  color: var(--text) !important;
  font-size: 1.75rem !important;
  font-weight: 700 !important;
  line-height: 1.2 !important;
}
[data-testid="stMetricDelta"] {
  font-size: 0.75rem !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
  background: transparent;
  border-bottom: 1px solid var(--border);
  gap: 2px;
  padding-bottom: 0;
}
.stTabs [data-baseweb="tab"] {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  color: var(--muted);
  font-size: 0.875rem;
  font-weight: 500;
  padding: 10px 18px 12px;
  transition: color 150ms ease, border-color 150ms ease;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text);
  background: transparent;
}
.stTabs [aria-selected="true"] {
  color: var(--text) !important;
  border-bottom-color: var(--accent) !important;
  background: transparent !important;
}
.stTabs [data-baseweb="tab-panel"] {
  padding-top: 1.5rem;
}

/* ── Divider ── */
hr {
  border: none;
  border-top: 1px solid var(--border) !important;
  margin: 1.5rem 0;
}

/* ── Buttons ── */
.stButton > button {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--text);
  font-size: 0.85rem;
  font-weight: 500;
  padding: 7px 16px;
  transition: background 150ms ease, border-color 150ms ease;
}
.stButton > button:hover {
  background: var(--border);
  border-color: var(--border2);
  color: var(--text);
}

/* ── Multiselect ── */
[data-testid="stMultiSelect"] [data-baseweb="tag"] {
  background: var(--surface2) !important;
  border: 1px solid var(--border2) !important;
  border-radius: 5px !important;
  color: var(--text) !important;
  font-size: 0.8rem !important;
}
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {
  background: var(--surface) !important;
  border-color: var(--border) !important;
  border-radius: 8px !important;
}

/* ── Date input / selectbox ── */
[data-testid="stDateInput"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
  background: var(--surface) !important;
  border-color: var(--border) !important;
  border-radius: 8px !important;
  color: var(--text) !important;
}
[data-testid="stDateInput"] input:focus,
[data-testid="stSelectbox"] [data-baseweb="select"]:focus-within > div {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 1px var(--accent) !important;
}
div[data-baseweb="popover"] [data-baseweb="menu"],
div[data-baseweb="calendar"] {
  background: var(--surface2) !important;
  border: 1px solid var(--border2) !important;
}

/* ── Alerts / info boxes ── */
[data-testid="stAlertContainer"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 9px !important;
}
[data-testid="stAlertContainer"] p { color: var(--text) !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0,0,0,0.2);
}

/* ── Captions / info ── */
.stCaption, [data-testid="stCaption"] {
  color: var(--muted) !important;
  font-size: 0.75rem !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

/* Section label utility */
.sec-label {
  color: var(--muted);
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0 0 30px;
}

/* Ticker stat row */
.ticker-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
  gap: 8px;
}
.ticker-stat:last-child { border-bottom: none; }
.ticker-stat .name  { color: var(--text); font-weight: 600; font-size: 0.875rem; }
.ticker-stat .count { color: var(--muted); font-size: 0.8rem; }
.ticker-stat .score { font-weight: 700; font-size: 0.875rem; }

/* Ticker summary card */
.ticker-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 14px 16px;
  margin-bottom: 10px;
  transition: border-color 150ms ease;
}
.ticker-card:hover { border-color: var(--border2); }
.ticker-card .card-name  { font-size: 1rem; font-weight: 700; color: var(--text); }
.ticker-card .card-score { font-size: 1.5rem; font-weight: 800; margin: 4px 0; }
.ticker-card .card-meta  { font-size: 0.72rem; color: var(--muted); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; }
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '<div style="margin-bottom:4px">'
        '<span style="font-size:1.1rem;font-weight:700;color:#e8edf5">SET Sentiment</span>'
        '</div>'
        '<div style="font-size:0.78rem;color:#475569;margin-bottom:20px;line-height:1.5">'
        'Thai stock sentiment<br>from Pantip.com'
        '</div>',
        unsafe_allow_html=True,
    )

    today = date.today()

    window_days: int = st.selectbox(
        "Rolling window",
        options=[1, 7, 14, 30],
        index=3,
        format_func=lambda x: f"{x} day{'s' if x > 1 else ''}",
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if st.button("↺  Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.markdown(
        '<div style="padding-top:16px;font-size:0.68rem;color:#5f6f7f;'
        'line-height:1.6;border-top:1px solid #1e3050">'
        'Updates every 3 h · GitHub Actions<br>'
        'Model: XLM-RoBERTa (Cardiff)'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="position:fixed;bottom:0.6rem;left:1.25rem;z-index:999;">'
        '<a href="https://github.com/kyawswarheinm/pantip-sentiment" target="_blank" '
        'style="font-size:0.86rem;color:#9fafbf;text-decoration:none;display:block;margin-bottom:3px">'
        'View <span style="color:#3b82f6;text-decoration:underline">GitHub Repository</span> ↗'
        '</a>'
        '<div style="font-size:0.7rem;color:#3a4f62">© 2026 Kyaw Swar Hein · MIT License</div>'
        '</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
start_str = "2024-01-01"
end_str   = today.isoformat()

rankings_df = load_sentiment_rankings(start_str, end_str)
volume_df   = load_volume_timeseries(start_str, end_str)
all_tickers = load_tickers()

# Tickers with data in this date range (for posts / alerts / compare options)
active_in_range: tuple[str, ...] = (
    tuple(rankings_df["ticker"].tolist()) if not rankings_df.empty else ()
)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_compare, tab_posts, tab_docs = st.tabs([
    "📊  Sentiment Dashboard",
    "🔍  Compare Tickers",
    "📰  Posts & Alerts",
    "📚  Documentation & Analysis",
])

# ── Tab 1: Sentiment Dashboard ────────────────────────────────────────────
with tab_overview:
    if rankings_df.empty:
        st.info(
            "No scored data in this date range. "
            "Widen the date range or trigger a pipeline run.",
            icon="ℹ️",
        )
    else:
        col_main, col_side = st.columns([3, 2], gap="large")

        with col_main:
            st.markdown('<p class="sec-label">Sentiment Rankings — all tickers</p>',
                        unsafe_allow_html=True)
            render_sentiment_ranking(rankings_df)

        with col_side:
            st.markdown(
                f'<h1 style="font-size:1.5rem;font-weight:700;color:#e8edf5;margin-bottom:2px">'
                f'SET Sentiment Monitor</h1>'
                f'<p style="font-size:0.82rem;color:#475569;margin-bottom:16px">'
                f'{len(active_in_range)} tickers · all time'
                f'</p>',
                unsafe_allow_html=True,
            )

            metrics = load_summary_metrics(active_in_range, start_str, end_str)
            avg_s = metrics["avg_sentiment"]
            sent_label = "Bullish" if avg_s > 0.05 else "Bearish" if avg_s < -0.05 else "Neutral"
            sent_delta = (
                f"▲ {sent_label}" if avg_s > 0.05
                else f"▼ {sent_label}" if avg_s < -0.05
                else sent_label
            )
            most_bullish = rankings_df.iloc[0]["ticker"]
            most_bearish = rankings_df.iloc[-1]["ticker"]

            k1, k2 = st.columns(2)
            k1.metric("Total Posts",   f"{metrics['total_posts']:,}")
            k2.metric("Avg Sentiment", f"{avg_s:+.3f}", delta=sent_delta)
            k3, k4 = st.columns(2)
            k3.metric("Most Bullish",  most_bullish)
            k4.metric("Most Bearish",  most_bearish)

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            st.markdown('<p class="sec-label">Daily Activity</p>',
                        unsafe_allow_html=True)
            render_volume_chart(volume_df)

            # Top 5 by post volume
            st.markdown(
                '<p class="sec-label" style="margin-top:18px">Most Discussed</p>',
                unsafe_allow_html=True,
            )
            top5 = rankings_df.nlargest(5, "post_count")
            rows_html = ""
            for _, r in top5.iterrows():
                color = (
                    "#22c55e" if r["avg_sentiment"] > 0.05
                    else "#ef4444" if r["avg_sentiment"] < -0.05
                    else "#64748b"
                )
                rows_html += (
                    f'<div class="ticker-stat">'
                    f'<span class="name">{r["ticker"]}</span>'
                    f'<span class="count">{int(r["post_count"])} posts</span>'
                    f'<span class="score" style="color:{color}">{r["avg_sentiment"]:+.3f}</span>'
                    f'</div>'
                )
            st.markdown(rows_html, unsafe_allow_html=True)

            # Bottom 5 by sentiment (watchlist)
            bottom5 = rankings_df.nsmallest(5, "avg_sentiment")
            if not bottom5.empty:
                st.markdown(
                    '<p class="sec-label" style="margin-top:18px">Bearish Watch</p>',
                    unsafe_allow_html=True,
                )
                rows_html = ""
                for _, r in bottom5.iterrows():
                    rows_html += (
                        f'<div class="ticker-stat">'
                        f'<span class="name">{r["ticker"]}</span>'
                        f'<span class="count">{int(r["post_count"])} posts</span>'
                        f'<span class="score" style="color:#ef4444">{r["avg_sentiment"]:+.3f}</span>'
                        f'</div>'
                    )
                st.markdown(rows_html, unsafe_allow_html=True)

# ── Tab 2: Compare Tickers ────────────────────────────────────────────────
with tab_compare:
    available_for_compare = rankings_df["ticker"].tolist() if not rankings_df.empty else []

    compare_tickers: list[str] = st.multiselect(
        "Select tickers to compare",
        options=available_for_compare,
        default=[],
        placeholder="Type to search a ticker…",
        help="Only tickers with scored posts in the selected date range appear here. "
             "2–5 tickers give the clearest comparison.",
        label_visibility="collapsed",
    )

    if not compare_tickers:
        st.markdown(
            '<div style="text-align:center;padding:56px 0 40px;color:#334155">'
            '<div style="font-size:2rem;margin-bottom:12px;opacity:0.6">📈</div>'
            '<div style="font-size:0.95rem;font-weight:600;color:#475569">'
            'Select tickers above to compare sentiment trends'
            '</div>'
            '<div style="font-size:0.8rem;margin-top:6px;color:#334155">'
            'Tip: 2–5 tickers give the clearest picture'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        if len(compare_tickers) > 8:
            st.warning(
                f"Capped at 8 tickers for readability. "
                f"Showing first 8 of {len(compare_tickers)} selected.",
                icon="⚠️",
            )
            compare_tickers = compare_tickers[:8]

        tickers_tuple = tuple(compare_tickers)
        sentiment_df  = load_sentiment_timeseries(tickers_tuple, start_str, end_str, window_days)
        prices_df     = load_prices(tickers_tuple, start_str, end_str)

        st.markdown('<p class="sec-label">Sentiment trend</p>', unsafe_allow_html=True)
        render_sentiment_chart(sentiment_df, prices_df, compare_tickers)

        # Per-ticker summary cards
        if not rankings_df.empty:
            ticker_stats = (
                rankings_df[rankings_df["ticker"].isin(compare_tickers)]
                .set_index("ticker")
            )
            st.markdown(
                '<p class="sec-label" style="margin-top:20px">Ticker summary (Sentiment)</p>',
                unsafe_allow_html=True,
            )
            ncols = min(len(compare_tickers), 4)
            card_cols = st.columns(ncols)
            for i, ticker in enumerate(compare_tickers):
                if ticker not in ticker_stats.index:
                    continue
                r     = ticker_stats.loc[ticker]
                sent  = r["avg_sentiment"]
                color = (
                    "#22c55e" if sent > 0.05
                    else "#ef4444" if sent < -0.05
                    else "#64748b"
                )
                label = "Bullish" if sent > 0.05 else "Bearish" if sent < -0.05 else "Neutral"
                with card_cols[i % ncols]:
                    st.markdown(
                        f'<div class="ticker-card">'
                        f'<div class="card-name">{ticker}</div>'
                        f'<div class="card-score" style="color:{color}">{sent:+.3f}</div>'
                        f'<div class="card-meta">'
                        f'{int(r["post_count"])} posts &nbsp;·&nbsp; '
                        f'<span style="color:{color}">{label}</span>'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            st.markdown(
                '<div style="font-size:0.9rem;color:#cccccc;line-height:1.7;margin-top:8px">'
                '&bull; <b>Score (−1 to +1)</b> — average sentiment across all scored posts '
                'mentioning the ticker, computed by XLM-RoBERTa from Pantip.com threads. '
                'Not a market price or analyst rating.<br>'
                '&bull; <b>Post count</b> — number of Pantip threads mentioning this ticker '
                'that were successfully scraped and scored by the pipeline.'
                '</div>',
                unsafe_allow_html=True,
            )

# ── Tab 3: Posts & Alerts ─────────────────────────────────────────────────
with tab_posts:
    if not active_in_range:
        st.info("No data in selected date range.", icon="ℹ️")
    else:
        # Ticker filter scoped to this tab
        filter_tickers = st.multiselect(
            "Filter by ticker",
            options=list(active_in_range),
            default=[],
            placeholder="All tickers — type to filter…",
            label_visibility="collapsed",
        )
        tickers_for_posts = tuple(filter_tickers) if filter_tickers else active_in_range

        posts_df = load_recent_posts(tickers_for_posts, start_str, end_str, limit=200)
        st.markdown('<p class="sec-label">Recent posts</p>', unsafe_allow_html=True)
        render_posts_feed(posts_df)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown('<p class="sec-label">Alert history</p>', unsafe_allow_html=True)
        alerts_df = load_alerts(tickers_for_posts)
        render_alert_banner(alerts_df)

# ── Tab 4: Documentation & Analysis ───────────────────────────────────────
with tab_docs:
    render_documentation_tab()
