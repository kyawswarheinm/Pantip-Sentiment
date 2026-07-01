"""
Regenerate the analysis charts embedded in README.md from live Turso data.

Not part of the runtime pipeline — a documentation-maintenance script.
Run after a significant data update to keep the README's charts current:

    python -m scripts.generate_readme_charts

Requires kaleido (not a runtime dependency; install separately:
`pip install kaleido`). All charts use the same Plotly figure builders as the
live dashboard tab (dashboard/charts.py), exported to PNG via kaleido.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.charts import (
    build_automation_pipeline_figure,
    build_confidence_figure,
    build_data_flow_diagram,
    build_funnel_figure,
    build_match_method_figure,
    build_scoring_cadence_figure,
    build_sentiment_distribution_figure,
    build_ticker_concentration_figure,
)
from db.client import get_client

OUT_DIR = ROOT / "docs" / "charts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ACCENT = "#3b82f6"
AMBER  = "#f59e0b"
GREEN  = "#22c55e"


def chart_data_flow_diagram(db) -> None:
    scraped = db.fetchall("SELECT COUNT(*) c FROM posts")[0]["c"]
    linked = db.fetchall("SELECT COUNT(DISTINCT post_id) c FROM post_tickers")[0]["c"]
    scored = db.fetchall(
        "SELECT COUNT(DISTINCT pt.post_id) c FROM post_tickers pt "
        "JOIN scores s ON s.post_ticker_id = pt.id"
    )[0]["c"]
    scored_rows = db.fetchall("SELECT COUNT(*) c FROM scores")[0]["c"]
    alerts_n = db.fetchall("SELECT COUNT(*) c FROM alerts")[0]["c"]

    fig = build_data_flow_diagram(scraped, linked, scored, scored_rows, alerts_n)
    fig.write_image(OUT_DIR / "data_flow_diagram.png", scale=2)
    print(f"data_flow_diagram: scraped={scraped} linked={linked} "
          f"scored_posts={scored} scored_rows={scored_rows} alerts={alerts_n}")


def chart_automation_pipeline() -> None:
    fig = build_automation_pipeline_figure()
    fig.write_image(OUT_DIR / "automation_pipeline.png", scale=2)
    print("automation_pipeline: drawn")


def chart_pipeline_funnel(db) -> None:
    scraped = db.fetchall("SELECT COUNT(*) c FROM posts")[0]["c"]
    linked = db.fetchall(
        "SELECT COUNT(DISTINCT post_id) c FROM post_tickers"
    )[0]["c"]
    scored = db.fetchall(
        "SELECT COUNT(DISTINCT pt.post_id) c FROM post_tickers pt "
        "JOIN scores s ON s.post_ticker_id = pt.id"
    )[0]["c"]

    fig = build_funnel_figure(
        ["Scraped posts", "Linked to ≥ 1 ticker", "Scored by NLP"],
        [scraped, linked, scored],
        [ACCENT, AMBER, GREEN],
        interpretation=(
            "Most loss happens at Linked → Scored — the fuzzy entity-matcher floods the "
            "queue with low-precision matches that free-tier compute can't clear."
        ),
    )
    fig.write_image(OUT_DIR / "pipeline_funnel.png", scale=2)
    print(f"pipeline_funnel: scraped={scraped} linked={linked} scored={scored}")


def chart_match_method_composition(db) -> None:
    all_methods = db.fetchall(
        "SELECT match_method, COUNT(*) c FROM post_tickers GROUP BY match_method"
    )
    scored_methods = db.fetchall(
        "SELECT pt.match_method, COUNT(*) c FROM post_tickers pt "
        "JOIN scores s ON s.post_ticker_id = pt.id GROUP BY pt.match_method"
    )
    all_map = {r["match_method"]: r["c"] for r in all_methods}
    scored_map = {r["match_method"]: r["c"] for r in scored_methods}
    methods = ["exact", "alias", "fuzzy"]
    all_total = sum(all_map.values()) or 1
    scored_total = sum(scored_map.values()) or 1

    fig = build_match_method_figure(
        methods=methods,
        all_pct=[all_map.get(m, 0) / all_total * 100 for m in methods],
        scored_pct=[scored_map.get(m, 0) / scored_total * 100 for m in methods],
        all_n=all_total,
        scored_n=scored_total,
    )
    fig.write_image(OUT_DIR / "match_method_composition.png", scale=2)
    print(f"match_method: all={all_map} scored={scored_map}")


def chart_confidence_threshold(db) -> None:
    rows = db.fetchall("SELECT confidence FROM scores")
    vals = [r["confidence"] for r in rows]
    fig = build_confidence_figure(vals, threshold=0.65)
    fig.write_image(OUT_DIR / "confidence_threshold.png", scale=2)
    below = sum(1 for v in vals if v < 0.65)
    print(f"confidence: below_0.65={below}/{len(vals)}")


def chart_ticker_concentration(db) -> None:
    rows = db.fetchall(
        """
        SELECT pt.ticker, COUNT(DISTINCT pt.post_id) c
        FROM post_tickers pt JOIN scores s ON s.post_ticker_id = pt.id
        GROUP BY pt.ticker ORDER BY c DESC
        """
    )
    total = sum(r["c"] for r in rows) or 1
    hhi = sum((r["c"] / total) ** 2 for r in rows) * 10000
    top = rows[:15]
    top_asc = top[::-1]  # ascending for horizontal bar (bottom = smallest)

    fig = build_ticker_concentration_figure(
        tickers=[r["ticker"] for r in top_asc],
        shares=[r["c"] / total * 100 for r in top_asc],
        counts=[r["c"] for r in top_asc],
        hhi=hhi,
        n_total_tickers=len(rows),
    )
    fig.write_image(OUT_DIR / "ticker_concentration.png", scale=2)
    print(f"ticker_concentration: n_tickers={len(rows)} hhi={hhi:.0f} "
          f"top5_share={sum(r['c'] for r in rows[:5])/total*100:.1f}%")


def chart_sentiment_distribution(db) -> None:
    rows = db.fetchall(
        "SELECT label, COUNT(*) c, AVG(confidence) avg_conf FROM scores GROUP BY label"
    )
    order = ["positive", "neutral", "negative"]
    by_label = {r["label"]: r for r in rows}

    fig = build_sentiment_distribution_figure(
        labels=order,
        counts=[by_label[l]["c"] if l in by_label else 0 for l in order],
        avg_confs=[by_label[l]["avg_conf"] if l in by_label else 0.0 for l in order],
    )
    fig.write_image(OUT_DIR / "sentiment_distribution.png", scale=2)
    print(f"sentiment_distribution: {by_label}")


def chart_scoring_cadence(db) -> None:
    rows = db.fetchall("SELECT date(scored_at) d, COUNT(*) c FROM scores GROUP BY d ORDER BY d")
    fig = build_scoring_cadence_figure(
        dates=[r["d"] for r in rows],
        counts=[r["c"] for r in rows],
    )
    fig.write_image(OUT_DIR / "scoring_cadence.png", scale=2)
    print(f"scoring_cadence: {dict(zip([r['d'] for r in rows], [r['c'] for r in rows]))}")


def chart_engagement_scatter(db) -> None:
    """Engagement scatter kept separate — uses Plotly subplots, inline here."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    BG = "#080e1d"
    PLOT_BG = "#0d1526"
    BORDER = "#1e2f4a"
    TEXT = "#e8edf5"
    MUTED = "#94a3b8"
    SUBTLE = "#475569"
    _GREEN = "#22c55e"
    _RED = "#ef4444"
    FONT = "Inter, system-ui, sans-serif"

    rows = db.fetchall(
        """
        SELECT p.replies, s.sentiment, s.confidence, s.label
        FROM scores s
        JOIN post_tickers pt ON pt.id = s.post_ticker_id
        JOIN posts p ON p.post_id = pt.post_id
        """
    )
    threshold = 0.65
    color_map = {"positive": _GREEN, "neutral": SUBTLE, "negative": _RED}
    facets = [
        (f"confidence ≥ {threshold}", [r for r in rows if r["confidence"] >= threshold]),
        (f"confidence < {threshold}", [r for r in rows if r["confidence"] < threshold]),
    ]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        subplot_titles=[f"{t}  (n={len(d):,})" for t, d in facets],
        vertical_spacing=0.14,
    )
    for row_i, (_, facet_rows) in enumerate(facets, start=1):
        for label in ("neutral", "negative", "positive"):
            xs = [r["sentiment"] for r in facet_rows if r["label"] == label]
            ys = [r["replies"] or 0 for r in facet_rows if r["label"] == label]
            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys, mode="markers",
                    marker=dict(size=7, color=color_map[label], opacity=0.65),
                    name=label.capitalize(), legendgroup=label,
                    showlegend=(row_i == 1),
                    hovertemplate=f"<b>{label.capitalize()}</b><br>%{{x:.2f}}<br>%{{y}} replies<extra></extra>",
                ),
                row=row_i, col=1,
            )
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG,
        font=dict(family=FONT, color=TEXT),
        height=680, width=1000,
        margin=dict(l=50, r=20, t=40, b=50),
        legend=dict(orientation="h", y=1.08, x=1, xanchor="right",
                    font=dict(size=10, color=MUTED), bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(range=[-1.08, 1.08], gridcolor=BORDER,
                     tickfont=dict(size=10, color=MUTED),
                     zeroline=True, zerolinecolor=BORDER)
    fig.update_yaxes(gridcolor=BORDER, tickfont=dict(size=10, color=MUTED))
    fig.update_xaxes(title=dict(text="Sentiment (−1 to +1)",
                                font=dict(size=10, color=MUTED)), row=2, col=1)
    for ann in fig["layout"]["annotations"]:
        ann["font"] = dict(size=12, color=TEXT)
        ann["x"] = 0
        ann["xanchor"] = "left"

    fig.write_image(OUT_DIR / "engagement_scatter.png", scale=2)
    hi = len(facets[0][1])
    lo = len(facets[1][1])
    print(f"engagement_scatter: hi_conf_n={hi} lo_conf_n={lo}")


def main() -> None:
    db = get_client()
    try:
        chart_data_flow_diagram(db)
        chart_automation_pipeline()
        chart_pipeline_funnel(db)
        chart_match_method_composition(db)
        chart_confidence_threshold(db)
        chart_ticker_concentration(db)
        chart_sentiment_distribution(db)
        chart_scoring_cadence(db)
        chart_engagement_scatter(db)
    finally:
        db.close()
    print(f"\nCharts written to {OUT_DIR}")


if __name__ == "__main__":
    main()
