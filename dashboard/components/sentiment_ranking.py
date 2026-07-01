"""Market overview: ranking bar chart + daily volume sparkline."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _bar_color(val: float) -> str:
    if val >  0.25: return "#16a34a"
    if val >  0.05: return "#22c55e"
    if val < -0.25: return "#b91c1c"
    if val < -0.05: return "#ef4444"
    return "#475569"


def render_sentiment_ranking(df: pd.DataFrame) -> None:
    """Horizontal bar chart — all tickers ranked by avg sentiment, most positive at top."""
    if df.empty:
        st.info("No sentiment data for the selected date range.")
        return

    df = df.sort_values("avg_sentiment", ascending=True)
    colors = [_bar_color(v) for v in df["avg_sentiment"]]

    fig = go.Figure(go.Bar(
        x=df["avg_sentiment"],
        y=df["ticker"],
        orientation="h",
        marker_color=colors,
        marker_line_width=0,
        text=[f"{v:+.2f}" for v in df["avg_sentiment"]],
        textposition="outside",
        textfont=dict(size=9, color="#64748b", family="Inter, system-ui, sans-serif"),
        customdata=df[["post_count"]].values,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Avg sentiment: %{x:+.3f}<br>"
            "Posts: %{customdata[0]}<extra></extra>"
        ),
    ))

    n = len(df)
    height = max(360, n * 24 + 56)

    fig.update_layout(
        xaxis=dict(
            range=[-1.35, 1.35],
            zeroline=True,
            zerolinecolor="#334155",
            zerolinewidth=1,
            gridcolor="#1a2540",
            tickformat="+.1f",
            tickfont=dict(size=10, color="#475569", family="Inter, system-ui, sans-serif"),
            title=None,
        ),
        yaxis=dict(
            tickfont=dict(size=10, color="#94a3b8", family="Inter, system-ui, sans-serif"),
            title=None,
            ticklabelposition="outside left",
        ),
        plot_bgcolor="#0d1526",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color="#e2e8f0"),
        height=height,
        margin=dict(l=0, r=56, t=8, b=8),
        showlegend=False,
        bargap=0.35,
    )

    # Reference lines at ±0.1 and ±0.3
    for x_val, color in [(-0.3, "#b91c1c"), (-0.1, "#7f1d1d"),
                          ( 0.1, "#14532d"), ( 0.3, "#16a34a")]:
        fig.add_vline(x=x_val, line_dash="dot", line_color=color,
                      line_width=1, opacity=0.35)

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_volume_chart(df: pd.DataFrame) -> None:
    """Area sparkline — daily post activity over the selected window."""
    if df.empty:
        st.caption("No activity data.")
        return

    fig = go.Figure(go.Scatter(
        x=list(df["day"]),
        y=df["post_count"],
        mode="lines",
        fill="tozeroy",
        line=dict(color="#3b82f6", width=1.5, shape="spline"),
        fillcolor="rgba(59,130,246,0.12)",
        hovertemplate="%{x|%d %b}<br><b>%{y} posts</b><extra></extra>",
    ))

    fig.update_layout(
        xaxis=dict(
            type="date",
            tickformat="%d %b",
            gridcolor="#1a2540",
            tickfont=dict(size=9, color="#475569"),
            title=None,
            showline=False,
        ),
        yaxis=dict(
            gridcolor="#1a2540",
            tickfont=dict(size=9, color="#475569"),
            title=None,
            rangemode="tozero",
        ),
        plot_bgcolor="#0d1526",
        paper_bgcolor="rgba(0,0,0,0)",
        height=160,
        margin=dict(l=0, r=0, t=4, b=0),
        showlegend=False,
        hovermode="x unified",
    )

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
