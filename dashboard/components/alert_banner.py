"""Alert history and open-alert banners."""
from __future__ import annotations

import pandas as pd
import streamlit as st

_RULE_LABEL = {
    "zscore":       "Sentiment spike",
    "volume_surge": "Volume surge",
}


def render_alert_banner(df: pd.DataFrame) -> None:
    if df.empty:
        st.markdown(
            '<div style="background:#0d1f12;border:1px solid #166534;border-radius:8px;'
            'padding:12px 16px;color:#4ade80;font-size:0.875rem">'
            '✓ No alerts for the selected tickers and date range.</div>',
            unsafe_allow_html=True,
        )
        return

    open_alerts = df[df["resolved"] == 0] if "resolved" in df.columns else pd.DataFrame()
    for _, row in open_alerts.iterrows():
        rule  = row.get("rule_type", "")
        label = _RULE_LABEL.get(rule, rule)
        ticker = row.get("ticker", "")
        val   = row.get("trigger_value", 0)
        threshold = row.get("threshold_used", 0)

        if rule == "zscore":
            msg = f"**{ticker}** — {label}: Z = {val:.2f} (threshold {threshold:.1f})"
        elif rule == "volume_surge":
            msg = f"**{ticker}** — {label}: {val:.1f}× average (threshold {threshold:.1f}×)"
        else:
            msg = f"**{ticker}** — {label}: {val:.2f}"

        st.warning(msg, icon="⚠️")

    display = df.copy()
    if "resolved" in display.columns:
        display["resolved"] = display["resolved"].map({0: "Open", 1: "Resolved"})
    if "rule_type" in display.columns:
        display["rule_type"] = display["rule_type"].map(_RULE_LABEL).fillna(display["rule_type"])

    st.dataframe(
        display.rename(columns={
            "ticker":         "Ticker",
            "rule_type":      "Rule",
            "trigger_value":  "Value",
            "threshold_used": "Threshold",
            "fired_at":       "Fired",
            "resolved":       "Status",
        }),
        width="stretch",
        hide_index=True,
        column_config={
            "Value":     st.column_config.NumberColumn(format="%.3f"),
            "Threshold": st.column_config.NumberColumn(format="%.2f"),
        },
    )
