"""Compare-mode chart: clean multi-line sentiment (+ optional price) for 2-8 tickers."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Distinct, accessible palette — 8 slots
_PALETTE = [
    "#3b82f6",  # blue
    "#22c55e",  # green
    "#f59e0b",  # amber
    "#a78bfa",  # violet
    "#38bdf8",  # sky
    "#fb923c",  # orange
    "#f472b6",  # pink
    "#34d399",  # emerald
]


def render_sentiment_chart(
    sentiment_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    selected_tickers: list[str],
) -> None:
    if sentiment_df.empty:
        st.info("No sentiment data for the selected tickers and date range.")
        return

    fig = go.Figure()

    # Legend key — ghost traces explaining line styles
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        name="Sentiment",
        mode="lines+markers",
        line=dict(color="#94a3b8", width=2),
        marker=dict(size=6, color="#94a3b8"),
        legendrank=0,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        name="Price overlay",
        mode="lines",
        line=dict(color="#94a3b8", width=1.5, dash="dot"),
        legendrank=1,
        hoverinfo="skip",
    ))

    for i, ticker in enumerate(selected_tickers):
        if ticker not in sentiment_df.columns:
            continue
        color = _PALETTE[i % len(_PALETTE)]

        fig.add_trace(go.Scatter(
            x=list(sentiment_df.index),
            y=sentiment_df[ticker],
            name=ticker,
            mode="lines+markers",
            line=dict(color=color, width=2, shape="spline"),
            marker=dict(size=5, color=color),
            yaxis="y1",
            legendrank=100 + i,
            hovertemplate=(
                f"<b>{ticker}</b><br>"
                "%{x|%d %b %Y}<br>"
                "Sentiment: %{y:+.3f}"
                "<extra></extra>"
            ),
        ))

    if not prices_df.empty:
        for i, ticker in enumerate(selected_tickers):
            if ticker not in prices_df.columns:
                continue
            color = _PALETTE[i % len(_PALETTE)]
            fig.add_trace(go.Scatter(
                x=list(prices_df.index),
                y=prices_df[ticker],
                name=f"{ticker} price",
                line=dict(color=color, width=1, dash="dot"),
                yaxis="y2",
                opacity=0.5,
                hoverinfo="skip",
                showlegend=False,
            ))

    fig.add_hrect(y0=-0.05, y1=0.05, fillcolor="#475569", opacity=0.08,
                  line_width=0, layer="below")
    fig.add_hline(y=0, line_color="#334155", line_width=1)

    fig.update_layout(
        xaxis=dict(
            type="date",
            tickformat="%d %b",
            gridcolor="#1a2540",
            tickfont=dict(size=10, color="#475569"),
            title=None,
            showline=False,
            showspikes=True,
            spikecolor="#475569",
            spikethickness=1,
            spikemode="across",
            spikedash="dot",
        ),
        yaxis=dict(
            title=dict(text="Sentiment (−1 to +1)", font=dict(size=11, color="#64748b")),
            range=[-1.15, 1.15],
            zeroline=False,
            gridcolor="#1a2540",
            tickfont=dict(size=10, color="#64748b"),
        ),
        yaxis2=dict(
            title=dict(text="Price (฿)", font=dict(size=11, color="#475569")),
            overlaying="y",
            side="right",
            showgrid=False,
            tickfont=dict(size=10, color="#475569"),
        ),
        legend=dict(
            orientation="h",
            y=-0.18,
            x=0,
            font=dict(size=12, color="#94a3b8"),
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
            tracegroupgap=0,
        ),
        plot_bgcolor="#0d1526",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color="#e2e8f0"),
        hovermode="closest",
        hoverdistance=20,
        height=380,
        margin=dict(l=0, r=0, t=8, b=40),
    )

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.markdown(
        '<div style="font-size:0.9rem;color:#cccccc;line-height:1.7;margin-top:4px">'
        '<b style="color:#cccccc">How the data is sourced</b><br>'
        '&bull; <b>Sentiment (Solid Lines)</b> — rolling average of post-level scores from '
        '<code>cardiffnlp/twitter-xlm-roberta-base-sentiment</code> (XLM-RoBERTa), '
        'applied to Pantip.com investment threads scraped every 3 hours via GitHub Actions. '
        'Each data point is one day\'s smoothed score on a −1 (bearish) to +1 (bullish) scale.<br>'
        '&bull; <b>Price overlay (Dash Lines)</b> — actual daily closing price (฿) for the '
        'SET-listed ticker, fetched from <code>yfinance</code> during each pipeline run.<br>'
        '&bull; <b>Dots on sentiment lines</b> — each dot marks one day\'s rolling-average '
        'value. The rolling window (configurable in the sidebar) smooths out day-to-day noise. '
        '</div>',
        unsafe_allow_html=True,
    )
