"""Recent Pantip posts feed with sentiment badges and clickable links."""
from __future__ import annotations

import pandas as pd
import streamlit as st

_BADGE = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}
_COLOR = {"positive": "#22c55e", "neutral": "#64748b", "negative": "#ef4444"}


def render_posts_feed(df: pd.DataFrame, limit: int = 100) -> None:
    if df.empty:
        st.markdown(
            '<div style="text-align:center;padding:40px 0;color:#475569">'
            '<div style="font-size:1.5rem;margin-bottom:8px">📭</div>'
            '<div style="color:#64748b;font-size:0.9rem">No posts found for the selected filters.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    display = df.head(limit).copy()
    display["sentiment_label"] = display["label"].map(
        lambda l: f"{_BADGE.get(l, '')} {l.capitalize()}"
    )
    display["score"] = display["sentiment"].round(3)
    display["title_th"] = display["title_th"].str.slice(0, 90)
    display["link"] = display["url"]

    cols = ["posted_at", "ticker", "title_th", "sentiment_label", "score", "replies", "link"]
    available = [c for c in cols if c in display.columns]

    st.dataframe(
        display[available].rename(columns={
            "posted_at": "Posted",
            "ticker":    "Ticker",
            "title_th":  "Title",
            "sentiment_label": "Sentiment",
            "score":     "Score",
            "replies":   "Replies",
            "link":      "Link",
        }),
        width="stretch",
        height=360,
        hide_index=True,
        column_config={
            "Link": st.column_config.LinkColumn("Link", display_text="↗"),
            "Score": st.column_config.NumberColumn(format="%.3f"),
            "Replies": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.caption(f"Showing {min(limit, len(df))} of {len(df):,} posts")
