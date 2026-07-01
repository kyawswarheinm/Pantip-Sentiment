"""Shared Plotly figure builders.

Used by both the live dashboard tab (dashboard/components/documentation.py,
via st.plotly_chart) and the README chart generator
(scripts/generate_readme_charts.py, via fig.write_image + kaleido), so the
two stay visually identical instead of drifting apart as separate
implementations.
"""
from __future__ import annotations

import textwrap

import plotly.graph_objects as go

# Palette — matches dashboard/app.py CSS custom-property tokens
BG = "#080e1d"
PLOT_BG = "#0d1526"
SURFACE = "#0d1526"
BORDER = "#1e3050"
TEXT = "#e8edf5"
MUTED = "#94a3b8"
SUBTLE = "#475569"
ACCENT = "#3b82f6"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
VIOLET = "#a78bfa"
SKY = "#38bdf8"
ORANGE = "#fb923c"
TURSO = "#4FF8D2"

FONT_FAMILY = "Inter, system-ui, sans-serif"


# ---------------------------------------------------------------------------
# Funnel — trapezoid stages + a side "conversion readout" panel
# ---------------------------------------------------------------------------

def build_funnel_figure(
    stages: list[str], values: list[int], colors: list[str],
    interpretation: str = "", fig_width: int = 1000,
) -> go.Figure:
    fig = go.Figure(go.Funnel(
        y=stages,
        x=values,
        marker=dict(color=colors, line=dict(color=BG, width=2)),
        textinfo="value+percent initial",
        textposition="inside",
        textfont=dict(color="#0b1220", size=13, family=FONT_FAMILY),
        connector=dict(line=dict(color=BORDER, width=1.2)),
    ))

    overall_pct = (values[-1] / values[0] * 100) if values[0] else 0.0
    drops = [
        (stages[i], stages[i + 1], 1 - values[i + 1] / values[i])
        for i in range(len(values) - 1) if values[i]
    ]
    worst = max(drops, key=lambda d: d[2]) if drops else None

    px0 = 0.64
    fig.add_shape(type="rect", xref="paper", yref="paper",
                  x0=px0, x1=1.0, y0=0.0, y1=1.0,
                  fillcolor=SURFACE, line=dict(color=BORDER, width=1), layer="below")

    # Manual word-wrap (kaleido's static renderer doesn't reliably honor
    # annotation `width` auto-wrap), sized for a ~0.32-paper-fraction-wide panel.
    wrap_chars = max(int(panel_text_px := (1.0 - px0 - 0.07) * fig_width / 5.6), 20)

    def _wrapped(text: str) -> tuple[str, int]:
        lines = textwrap.wrap(text, width=wrap_chars) or [""]
        return "<br>".join(lines), len(lines)

    blocks = [("CONVERSION READOUT", 10.5, MUTED, 400)]
    blocks.append((f"{overall_pct:.1f}%", 30, TEXT, 700))
    blocks.append((f"{stages[-1].lower()} from {stages[0].lower()}", 10.5, MUTED, 400))
    blocks.append(("__GAP__", 0, None, 0))
    blocks.append(("STRONGEST LOSS ZONE", 10.5, ACCENT, 400))
    blocks.append((f"{worst[0]} → {worst[1]}" if worst else "—", 13, TEXT, 700))
    blocks.append((f"{worst[2] * 100:.0f}% drop at this stage" if worst else "", 10.5, MUTED, 400))
    if interpretation:
        blocks.append(("__GAP__", 0, None, 0))
        blocks.append(("INTERPRETATION", 10.5, ACCENT, 400))
        blocks.append((interpretation, 10, MUTED, 400))

    cursor = 0.96
    for text, size, color, weight in blocks:
        if text == "__GAP__":
            cursor -= 0.05
            continue
        display_text, n_lines = _wrapped(text) if size <= 13 and len(text) > 28 else (text, 1)
        line_h = (size / 10.0) * 0.052
        cursor -= line_h * 0.6
        fig.add_annotation(
            xref="paper", yref="paper", x=px0 + 0.045, y=cursor, xanchor="left", yanchor="top",
            showarrow=False, text=display_text, align="left",
            font=dict(size=size, color=color, family=FONT_FAMILY, weight=weight),
        )
        cursor -= line_h * (n_lines - 1) + line_h * 0.75

    fig.update_layout(
        xaxis=dict(domain=[0.0, 0.58], visible=False),
        yaxis=dict(tickfont=dict(size=12.5, color=TEXT, family=FONT_FAMILY)),
        plot_bgcolor=PLOT_BG,
        paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        margin=dict(l=0, r=0, t=16, b=28),
        width=fig_width,
        height=360,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Shared box-flowchart primitives
# ---------------------------------------------------------------------------

def _step_box(fig: go.Figure, x0: float, x1: float, y0: float, y1: float,
              title: str, color: str, subtitle: str = "") -> None:
    fig.add_shape(
        type="rect", xref="x", yref="y", x0=x0, x1=x1, y0=y0, y1=y1,
        fillcolor=SURFACE, line=dict(color=color, width=1.4),
    )
    bh = y1 - y0
    cy = (y0 + y1) / 2 + (bh * 0.14 if subtitle else 0)
    fig.add_annotation(
        x=(x0 + x1) / 2, y=cy, xref="x", yref="y",
        text=title, showarrow=False, align="center",
        font=dict(size=12, color=color, family=FONT_FAMILY, weight=700),
    )
    if subtitle:
        fig.add_annotation(
            x=(x0 + x1) / 2, y=cy - bh * 0.37, xref="x", yref="y",
            text=subtitle, showarrow=False, align="center",
            font=dict(size=9.5, color=MUTED, family=FONT_FAMILY, weight=400),
        )


def _step_arrow(fig: go.Figure, x0: float, y0: float, x1: float, y1: float,
                 label: str = "", color: str = MUTED, label_dy: float = 0.18) -> None:
    fig.add_annotation(
        x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.4, arrowcolor=color,
        text="",
    )
    if label:
        fig.add_annotation(
            x=(x0 + x1) / 2, y=(y0 + y1) / 2 + label_dy, xref="x", yref="y",
            text=label, showarrow=False, align="center",
            font=dict(size=9.5, color=color, family=FONT_FAMILY, weight=400),
        )


# ---------------------------------------------------------------------------
# Data flow — Pantip.com (left) → posts (right), then vertical chain down
# ---------------------------------------------------------------------------

def build_data_flow_diagram(
    scraped: int, linked: int, scored: int, scored_rows: int, alerts_total: int,
    fig_width: int = 1100,
) -> go.Figure:
    """Pantip.com box on the left; horizontal arrow to posts; then vertical
    chain (posts → post_tickers → scores) runs straight down the centre;
    four downstream consumers fan out horizontally at the bottom.

    Arrow labels sit centred ON each arrow (bgcolor covers the line so the
    text floats cleanly without being pushed far to one side).
    """
    fig = go.Figure()

    BH  = 1.2   # box height — taller for readability
    BCX = 7.5   # centre-x of the vertical chain (posts / post_tickers / scores)
    BX0, BX1 = 5.5, 9.5  # left/right edges of the vertical-chain boxes

    # ── Top row: Pantip.com (left) and posts (right, same y) ────────────────
    PX0, PX1 = 0.5, 3.3   # Pantip.com narrow box
    y_row = (8.5, 8.5 + BH)          # (8.5, 9.7)
    row_cy = (y_row[0] + y_row[1]) / 2  # 9.1 — arrow / row centre

    _step_box(fig, PX0, PX1, y_row[0], y_row[1],
              "Pantip.com", TEXT, "5 Thai investment<br>tag pages")

    # Horizontal arrow Pantip.com → posts
    gap_cx = (PX1 + BX0) / 2   # midpoint of the gap = 4.4
    fig.add_annotation(
        x=BX0, y=row_cy, ax=PX1, ay=row_cy,
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.4, arrowcolor=MUTED,
        text="",
    )
    # Label sits above the horizontal arrow, centred in the gap between boxes
    fig.add_annotation(
        x=gap_cx, y=row_cy + 0.28, xref="x", yref="y",
        text="Selenium + BeautifulSoup<br>(scrape & clean)",
        showarrow=False, xanchor="center", align="center",
        font=dict(size=9.5, color=MUTED, family=FONT_FAMILY),
        bgcolor=BG, borderpad=2,
    )

    _step_box(fig, BX0, BX1, y_row[0], y_row[1],
              "posts", TURSO, f"{scraped:,} rows<br>Turso · LibSQL")

    # ── Vertical chain: gap == BH so each gap has room for a label ──────────
    GAP = BH   # 1.2 units between bottom of one box and top of next
    y_tick  = (y_row[0] - GAP - BH, y_row[0] - GAP)    # (6.1, 7.3)
    y_score = (y_tick[0] - GAP - BH, y_tick[0] - GAP)  # (3.7, 4.9)

    _step_box(fig, BX0, BX1, y_tick[0],  y_tick[1],
              "post_tickers", TURSO, f"{linked:,} linked<br>Turso · LibSQL")
    _step_box(fig, BX0, BX1, y_score[0], y_score[1],
              "scores", TURSO, f"{scored:,} posts / {scored_rows:,}<br>Turso · LibSQL")

    # Vertical arrows — label centred ON the arrow with bgcolor to cut through the line
    vert_chain = [
        (y_row[0],   y_tick[1],   "entity_match.py<br>(RapidFuzz, regex)"),
        (y_tick[0],  y_score[1],  "nlp/inference.py<br>(XLM-RoBERTa · Transformers)"),
    ]
    for src_y, dst_y, label in vert_chain:
        fig.add_annotation(                          # the arrow itself
            x=BCX, y=dst_y, ax=BCX, ay=src_y,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.4, arrowcolor=MUTED,
            text="",
        )
        fig.add_annotation(                          # label on the arrow
            x=BCX, y=(src_y + dst_y) / 2, xref="x", yref="y",
            text=label, showarrow=False, xanchor="center", align="center",
            font=dict(size=9.5, color=MUTED, family=FONT_FAMILY),
            bgcolor=BG, borderpad=3,
        )

    # ── Downstream consumers — fan out from scores bottom ───────────────────
    downstream = [
        ("Alert engine", f"{alerts_total} fired",  RED,    "alerts/spike_detector.py",  "NumPy Z-score"),
        ("Backtest",     "every 3 hours",             VIOLET, "backtest/correlation.py",   "yfinance + SciPy"),
        ("Kaggle export","every 3 hours",             SKY,    "kaggle/export.py",          "Kaggle API"),
        ("Dashboard",    "4 tabs",                  ORANGE, "dashboard/app.py",          "Streamlit + Plotly"),
    ]
    DBW = 3.0
    DS  = 0.5
    DY0 = 0.2
    DY1 = DY0 + BH
    n = len(downstream)
    total_dw = n * DBW + (n - 1) * DS
    dstart = BCX - total_dw / 2   # 0.75

    fan_src_x, fan_src_y = BCX, y_score[0]   # bottom-centre of scores = (7.5, 3.7)

    frac = 0.6
    for i, (title, subtitle, color, modpath, tool) in enumerate(downstream):
        dx0 = dstart + i * (DBW + DS)
        dcx = dx0 + DBW / 2
        _step_box(fig, dx0, dx0 + DBW, DY0, DY1, title, color, subtitle)

        fig.add_annotation(
            x=dcx, y=DY1, ax=fan_src_x, ay=fan_src_y,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.3, arrowcolor=color,
            text="",
        )
        lx = fan_src_x + (dcx   - fan_src_x) * frac
        ly = fan_src_y + (DY1   - fan_src_y) * frac
        fig.add_annotation(
            x=lx, y=ly, xref="x", yref="y", showarrow=False, align="center",
            text=f"{modpath}<br>({tool})",
            font=dict(size=8.5, color=color, family=FONT_FAMILY),
            bgcolor=BG, borderpad=1,
        )

    fig.update_layout(
        xaxis=dict(visible=False, range=[0.0, 15.5]),
        yaxis=dict(visible=False, range=[-0.2, 10.8]),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        margin=dict(l=10, r=10, t=10, b=10),
        width=fig_width,
        height=620,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Automation pipeline — two independent GitHub Actions workflow chains
# ---------------------------------------------------------------------------


def build_automation_pipeline_figure(fig_width: int = 1000) -> go.Figure:
    """Two GitHub Actions workflow chains as a clean step-box flowchart."""
    fig = go.Figure()

    lane1 = ["Checkout +\ninstall deps", "scraper.pantip\n(Selenium)",
             "nlp.inference\n(link + score)", "alerts.spike_\ndetector",
             "backtest.correlation\n(price + lag)", "kaggle.export\n(CSV upload)"]
    lane2 = ["Checkout +\ninstall deps", "kaggle.export\n(CSV upload)"]

    box_w, gap, box_h = 1.6, 0.55, 1.0
    y1, y2 = 2.6, 0.3

    for i, text in enumerate(lane1):
        x0 = i * (box_w + gap)
        _step_box(fig, x0, x0 + box_w, y1, y1 + box_h, text.replace("\n", "<br>"), ACCENT)
        if i > 0:
            _step_arrow(fig, x0 - gap, y1 + box_h / 2, x0, y1 + box_h / 2)

    for i, text in enumerate(lane2):
        x0 = i * (box_w + gap)
        _step_box(fig, x0, x0 + box_w, y2, y2 + box_h, text.replace("\n", "<br>"), MUTED)
        if i > 0:
            _step_arrow(fig, x0 - gap, y2 + box_h / 2, x0, y2 + box_h / 2)

    total_w = len(lane1) * (box_w + gap) - gap

    fig.add_annotation(
        x=0, y=y1 + box_h + 0.42, xref="x", yref="y", xanchor="left", showarrow=False,
        text="<b>scrape.yml</b> — every 3 hours&nbsp;&nbsp;(0 */3 * * *)",
        font=dict(size=13, color=TEXT, family=FONT_FAMILY),
    )
    fig.add_annotation(
        x=0, y=y2 + box_h + 0.42, xref="x", yref="y", xanchor="left", showarrow=False,
        text="<b>kaggle_export.yml</b> — Disabled",
        font=dict(size=13, color=MUTED, family=FONT_FAMILY),
    )
    note_x0, note_x1 = total_w - 4.6, total_w
    note_y0, note_y1 = y2 - 0.05, y2 + box_h + 0.05
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=note_x0, x1=note_x1, y0=note_y0, y1=note_y1,
                  fillcolor="rgba(0,0,0,0)", line=dict(color=BORDER, width=1, dash="dot"))
    note_lines = textwrap.wrap(
        "kaggle_export.yml is kept for testing the export step in isolation during development. "
        "scrape.yml already exports to Kaggle on every 3-hourly run.",
        width=42,
    )
    fig.add_annotation(
        x=(note_x0 + note_x1) / 2, y=(note_y0 + note_y1) / 2, xref="x", yref="y",
        xanchor="center", yanchor="middle", showarrow=False, align="center",
        text="<br>".join(note_lines),
        font=dict(size=10.5, color=MUTED, family=FONT_FAMILY),
    )

    fig.update_layout(
        xaxis=dict(visible=False, range=[-0.3, total_w + 0.3]),
        yaxis=dict(visible=False, range=[-0.2, y1 + box_h + 0.75]),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        margin=dict(l=10, r=10, t=10, b=10),
        width=fig_width,
        height=300,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Analysis charts — shared Plotly builders (used by docs tab + README export)
# ---------------------------------------------------------------------------

def build_match_method_figure(
    methods: list[str],
    all_pct: list[float],
    scored_pct: list[float],
    all_n: int,
    scored_n: int,
    fig_width: int = 900,
) -> go.Figure:
    """Grouped horizontal bar: entity-match method split for all links vs scored."""
    labels = [m.capitalize() for m in methods]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=all_pct, orientation="h",
        name=f"All ticker links (n={all_n:,})",
        marker_color=SUBTLE, offsetgroup=0,
        text=[f"{p:.0f}%" for p in all_pct], textposition="outside",
        textfont=dict(size=10.5, color=TEXT),
        hovertemplate="<b>%{y}</b><br>%{x:.1f}%% of all links<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=labels, x=scored_pct, orientation="h",
        name=f"Scored subset (n={scored_n:,})",
        marker_color=ACCENT, offsetgroup=1,
        text=[f"{p:.0f}%" for p in scored_pct], textposition="outside",
        textfont=dict(size=10.5, color=TEXT),
        hovertemplate="<b>%{y}</b><br>%{x:.1f}%% of scored<extra></extra>",
    ))
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        barmode="group",
        xaxis=dict(range=[0, 112], gridcolor=BORDER,
                   tickfont=dict(size=10, color=MUTED),
                   title=dict(text="Share of rows (%)", font=dict(size=10, color=MUTED))),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11, color=TEXT)),
        legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=10, color=MUTED),
                    bgcolor="rgba(0,0,0,0)"),
        height=280,
        margin=dict(l=0, r=12, t=8, b=50),
        width=fig_width,
    )
    return fig


def build_confidence_figure(
    values: list[float],
    threshold: float = 0.65,
    fig_width: int = 600,
) -> go.Figure:
    """Histogram of model confidence with threshold vline."""
    below = sum(1 for v in values if v < threshold)
    total = len(values)
    fig = go.Figure(go.Histogram(
        x=values, nbinsx=24, marker_color=ACCENT, opacity=0.85,
        hovertemplate="confidence %{x:.2f}<br>%{y} rows<extra></extra>",
    ))
    fig.add_vline(x=threshold, line_color=AMBER, line_width=1.6, line_dash="dash")
    fig.add_annotation(
        x=threshold - 0.02, yref="paper", y=0.96, xanchor="right", showarrow=False,
        text=f"threshold {threshold}",
        font=dict(size=9.5, color=AMBER, family=FONT_FAMILY),
    )
    if total:
        fig.add_annotation(
            xref="paper", yref="paper", x=0.02, y=0.96, xanchor="left", yanchor="top",
            showarrow=False, align="left",
            text=f"{below:,}/{total:,} rows ({below/total*100:.0f}%) below threshold",
            font=dict(size=9.5, color=TEXT, family=FONT_FAMILY),
            bgcolor=SURFACE, borderpad=3, bordercolor=BORDER,
        )
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        title=dict(text="Confidence Histogram", font=dict(size=13, color=TEXT), x=0, xanchor="left"),
        xaxis=dict(title=dict(text="Confidence", font=dict(size=10, color=MUTED)),
                   gridcolor=BORDER, tickfont=dict(size=10, color=MUTED)),
        yaxis=dict(title=dict(text="Scored rows", font=dict(size=10, color=MUTED)),
                   gridcolor=BORDER, tickfont=dict(size=10, color=MUTED)),
        height=280, bargap=0.05,
        margin=dict(l=0, r=12, t=36, b=8),
        width=fig_width, showlegend=False,
    )
    return fig


def build_sentiment_distribution_figure(
    labels: list[str],
    counts: list[int],
    avg_confs: list[float],
    fig_width: int = 600,
) -> go.Figure:
    """Bar chart of positive / neutral / negative label counts."""
    color_map = {"positive": GREEN, "neutral": SUBTLE, "negative": RED}
    total = sum(counts) or 1
    fig = go.Figure(go.Bar(
        x=[l.capitalize() for l in labels],
        y=counts,
        marker_color=[color_map.get(l, MUTED) for l in labels],
        text=[f"{int(c):,} ({c/total*100:.0f}%)<br>conf {ac:.2f}"
              for c, ac in zip(counts, avg_confs)],
        textposition="outside",
        textfont=dict(size=10.5, color=TEXT),
        hovertemplate="<b>%{x}</b><br>%{y} rows<extra></extra>",
    ))
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        title=dict(text="Sentiment Label Distribution", font=dict(size=13, color=TEXT), x=0, xanchor="left"),
        xaxis=dict(tickfont=dict(size=11, color=TEXT)),
        yaxis=dict(range=[0, max(counts) * 1.38] if counts else [0, 10],
                   gridcolor=BORDER, tickfont=dict(size=10, color=MUTED),
                   title=dict(text="Scored rows", font=dict(size=10, color=MUTED))),
        height=280, showlegend=False,
        margin=dict(l=0, r=12, t=36, b=8),
        width=fig_width,
    )
    return fig


def build_ticker_concentration_figure(
    tickers: list[str],
    shares: list[float],
    counts: list[int],
    hhi: float,
    n_total_tickers: int,
    fig_width: int = 900,
) -> go.Figure:
    """Horizontal bar chart of ticker concentration (top N scored tickers)."""
    max_share = max(shares) if shares else 10
    fig = go.Figure(go.Bar(
        x=shares, y=tickers, orientation="h",
        marker_color=ACCENT, marker_line_width=0,
        text=[f"{p:.1f}%  ({int(c)} posts)" for p, c in zip(shares, counts)],
        textposition="outside",
        textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>%{x:.1f}%%<extra></extra>",
    ))
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        xaxis=dict(range=[0, max_share * 1.42], gridcolor=BORDER,
                   tickfont=dict(size=10, color=MUTED),
                   title=dict(text="Share of scored posts (%)", font=dict(size=10, color=MUTED))),
        yaxis=dict(tickfont=dict(size=11, color=TEXT)),
        height=420,
        margin=dict(l=0, r=12, t=8, b=8),
        width=fig_width,
    )
    return fig


def build_lag_correlation_figure(
    df: "pd.DataFrame",
    ticker: str,
    fig_width: int = 900,
) -> go.Figure:
    """Bar chart of Pearson r at lags 0–5. Blue = p < 0.05 significant, grey = not."""
    import pandas as pd
    valid = df.dropna(subset=["pearson_r", "pearson_p"])
    lags = [f"Lag {int(r['lag'])}d" for _, r in valid.iterrows()]
    rs   = [float(r["pearson_r"]) for _, r in valid.iterrows()]
    ps   = [float(r["pearson_p"]) for _, r in valid.iterrows()]
    ns   = [int(r["n_obs"])       for _, r in valid.iterrows()]

    colors = [ACCENT if p < 0.05 else MUTED for p in ps]
    y_abs  = max((abs(r) for r in rs), default=0.1)

    fig = go.Figure(go.Bar(
        x=lags, y=rs,
        marker_color=colors,
        text=[f"r={r:+.3f}" for r in rs],
        textposition="outside",
        textfont=dict(size=10.5, color=TEXT),
        customdata=[[n, p] for n, p in zip(ns, ps)],
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Pearson r = %{y:.4f}<br>"
            "p = %{customdata[1]:.3f}<br>"
            "n = %{customdata[0]}<extra></extra>"
        ),
    ))
    fig.add_hline(y=0, line_color=BORDER, line_width=1)
    fig.update_layout(
        title=dict(
            text=f"Sentiment x Price Return Lag Correlation: {ticker}",
            font=dict(size=13, color=TEXT), x=0, xanchor="left",
        ),
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        xaxis=dict(tickfont=dict(size=11, color=TEXT)),
        yaxis=dict(
            title=dict(text="Pearson r", font=dict(size=10, color=MUTED)),
            gridcolor=BORDER, tickfont=dict(size=10, color=MUTED),
            range=[-(y_abs * 1.5 + 0.05), y_abs * 1.5 + 0.05],
            zeroline=True, zerolinecolor=BORDER, zerolinewidth=1,
        ),
        height=280,
        margin=dict(l=0, r=12, t=36, b=8),
        width=fig_width, showlegend=False,
    )
    return fig


def build_scoring_cadence_figure(
    dates: list[str],
    counts: list[int],
    fig_width: int = 900,
) -> go.Figure:
    """Bar chart of rows scored per day — reveals batch-y run cadence."""
    max_count = max(counts) if counts else 1
    fig = go.Figure(go.Bar(
        x=dates, y=counts,
        marker_color=VIOLET, marker_line_width=0,
        text=[f"{c:,}" for c in counts],
        textposition="outside",
        textfont=dict(size=9.5, color=TEXT),
        hovertemplate="%{x}<br>%{y} rows scored<extra></extra>",
    ))
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT_FAMILY, color=TEXT),
        xaxis=dict(tickangle=-20, tickfont=dict(size=10, color=MUTED), gridcolor=BORDER),
        yaxis=dict(range=[0, max_count * 1.22], gridcolor=BORDER,
                   tickfont=dict(size=10, color=MUTED),
                   title=dict(text="Rows scored", font=dict(size=10, color=MUTED))),
        height=300, bargap=0.35,
        margin=dict(l=0, r=12, t=8, b=50),
        width=fig_width, showlegend=False,
    )
    return fig
