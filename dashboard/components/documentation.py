"""Documentation & Analysis tab — pipeline diagrams + live analysis queries.

Mirrors the analysis in README.md, but computed live against the current
database on every cache refresh instead of being a point-in-time snapshot.
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.charts import (
    build_automation_pipeline_figure,
    build_confidence_figure,
    build_data_flow_diagram,
    build_funnel_figure,
    build_lag_correlation_figure,
    build_match_method_figure,
    build_scoring_cadence_figure,
    build_sentiment_distribution_figure,
    build_ticker_concentration_figure,
)
from dashboard.utils import (
    load_confidence_values,
    load_engagement_correlation,
    load_engagement_scatter_data,
    load_lag_correlation,
    load_match_method_breakdown,
    load_sentiment_date_stats,
    load_pipeline_funnel,
    load_scoring_cadence,
    load_sentiment_label_breakdown,
    load_ticker_concentration,
    load_tickers_with_prices,
)

_PLOT_BG = "#0d1526"
_GRID = "#1e3050"
_TEXT = "#e2e8f0"
_MUTED = "#64748b"
_ACCENT = "#3b82f6"
_GREEN = "#22c55e"
_RED = "#ef4444"
_AMBER = "#f59e0b"
_SUBTLE = "#475569"
_VIOLET = "#a78bfa"
_SKY = "#38bdf8"
_ORANGE = "#fb923c"


def _section_label(text: str, anchor: str = "") -> None:
    if anchor:
        st.markdown(f'<a id="{anchor}"></a>', unsafe_allow_html=True)
    st.markdown(f'<p class="sec-label" style="margin-top:4px; margin-bottom:30px">{text}</p>', unsafe_allow_html=True)


def _render_toc() -> None:
    # Offset all anchor jumps to clear Streamlit's fixed top bar (~52px) plus margin
    st.markdown(
        "<style>a[id]{display:block;scroll-margin-top:70px}</style>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div style="background:#0d1526;border:1px solid #1e3050;border-radius:10px;padding:18px 21px;margin-bottom:36px">
  <p style="text-align:center;color:#e2e8f0;font-size:1.0rem;letter-spacing:0.1em;text-transform:uppercase;margin:-4px 0 6px 0;font-weight:700">Table of Contents</p>

  <div style="display:flex;align-items:center;gap:10px;margin:4px 0 4px 0">
    <div style="flex:1;height:1px;background:#1e3050"></div>
    <span style="color:#606f6f;font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;white-space:nowrap">Automation Pipeline</span>
    <div style="flex:1;height:1px;background:#1e3050"></div>
  </div>

  <div style="margin-bottom:3px">
    <a href="#data-flow" style="color:#e8edf5;text-decoration:none;font-size:0.9rem;font-weight:500">—  Data Flow Diagram — Automated Pipeline</a>
  </div>
  <div style="border-left:2px solid #1e3050;margin-left:6px;padding-left:14px;margin-bottom:6px;margin-top:6px">
    <div style="margin-bottom:5px"><a href="#data-collection" style="color:#64748b;text-decoration:none;font-size:0.82rem">1. Data Collection</a></div>
    <div style="margin-bottom:5px"><a href="#preprocessing" style="color:#64748b;text-decoration:none;font-size:0.82rem">2. Preprocessing — Entity Matching</a></div>
    <div style="margin-bottom:5px"><a href="#nlp-model" style="color:#64748b;text-decoration:none;font-size:0.82rem">3. NLP Model — Sentiment Scoring</a></div>
    <div style="margin-bottom:5px"><a href="#downstream-usage" style="color:#64748b;text-decoration:none;font-size:0.82rem">4. Downstream Usage</a></div>
    <div style="margin-bottom:5px"><a href="#gh-actions-workflows" style="color:#64748b;text-decoration:none;font-size:0.82rem">5. GitHub Actions</a></div>
    </div>
<div style="margin-bottom:3px">
    <a href="#tools-stack" style="color:#e8edf5;text-decoration:none;font-size:0.9rem;font-weight:500">—  Tools &amp; Services Used</a>
  </div>

  <div style="display:flex;align-items:center;gap:10px;margin:4px 0 4px 0">
    <div style="flex:1;height:1px;background:#1e3050"></div>
    <span style="color:#606f6f;font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;white-space:nowrap">Analysis</span>
    <div style="flex:1;height:1px;background:#1e3050"></div>
  </div>

  <div style="margin-bottom:3px"><a href="#funnel" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Post-to-score conversion funnel</a></div>
  <div style="margin-bottom:3px"><a href="#entity-matching" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Entity-matching quality: all links vs. what got scored</a></div>
  <div style="margin-bottom:3px"><a href="#model-confidence" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Model confidence &amp; sentiment distribution</a></div>
  <div style="margin-bottom:3px"><a href="#ticker-concentration" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Ticker concentration</a></div>

  <div style="display:flex;align-items:center;gap:10px;margin:4px 0 4px 0">
    <div style="flex:1;height:1px;background:#1e3050"></div>
    <span style="color:#606f6f;font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;white-space:nowrap">Questions</span>
    <div style="flex:1;height:1px;background:#1e3050"></div>
  </div>

  <div style="margin-bottom:3px"><a href="#lag-correlation" style="color:#e8edf5;text-decoration:none;font-size:0.9rem;">—  <b>MAIN QUESTION:</b> Does sentiment predict price? (Lag correlation backtest)</a></div>
  <div style="margin-bottom:3px"><a href="#engagement" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  ADDITIONAL QUESTION: Does engagement correlate with sentiment?</a></div>

  <div style="display:flex;align-items:center;gap:10px;margin:4px 0 4px 0">
    <div style="flex:1;height:1px;background:#1e3050"></div>
    <span style="color:#606f6f;font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;white-space:nowrap">Additional Notes</span>
    <div style="flex:1;height:1px;background:#1e3050"></div>
  </div>

  <div style="margin-bottom:3px"><a href="#limitations" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Known limitations</a></div>
  <div><a href="#contributors" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Project Attribution</a></div>
  <div style="margin-bottom:3px"><a href="#research_paper" style="color:#e8edf5;text-decoration:none;font-size:0.9rem">—  Research Paper</a></div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_data_flow_diagram() -> None:
    f = load_pipeline_funnel()
    fig = build_data_flow_diagram(
        f["scraped"], f["linked"], f["scored"], f["scored_rows"], f["alerts_total"],
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    drop = (1 - f["scored"] / f["scraped"]) * 100 if f["scraped"] else 0
    st.caption(
        f"Tracking {f['tickers_total']} SET tickers. {drop:.0f}% of scraped posts never reach "
        f"a sentiment score — most have no text or mention no tracked stock."
    )


def _render_automation_pipeline() -> None:
    fig = build_automation_pipeline_figure()
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _render_funnel_detail() -> None:
    f = load_pipeline_funnel()
    fig = build_funnel_figure(
        ["Scraped posts", "Linked to ≥ 1 ticker", "Scored by NLP"],
        [f["scraped"], f["linked"], f["scored"]],
        [_ACCENT, _AMBER, _GREEN],
        interpretation=(
            "Most loss happens before linking — posts with no body text or no mention "
            "of a tracked stock never produce a ticker link and can't be scored."
        ),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _render_match_method() -> None:
    df = load_match_method_breakdown()
    if df.empty:
        st.info("No ticker-link data yet.")
        return

    fig = build_match_method_figure(
        methods=list(df["method"]),
        all_pct=list(df["all_pct"]),
        scored_pct=list(df["scored_pct"]),
        all_n=int(df["all_count"].sum()),
        scored_n=int(df["scored_count"].sum()),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    all_total = int(df["all_count"].sum())
    scored_total = int(df["scored_count"].sum())
    fuzzy_row = df[df["method"] == "fuzzy"]
    fuzzy_all_pct = float(fuzzy_row["all_pct"].iloc[0]) if not fuzzy_row.empty else 0.0
    fuzzy_scored_pct = float(fuzzy_row["scored_pct"].iloc[0]) if not fuzzy_row.empty else 0.0
    st.caption(
        f"All {all_total:,} ticker links vs. the {scored_total:,} that made it through scoring. "
        f"Fuzzy matches are {fuzzy_all_pct:.0f}% of all links and "
        f"{fuzzy_scored_pct:.0f}% of scored ones."
    )


def _render_confidence_and_labels() -> None:
    col1, col2 = st.columns(2, gap="large")

    with col1:
        conf_df = load_confidence_values()
        if conf_df.empty:
            st.info("No scores yet.")
        else:
            vals = list(conf_df["confidence"])
            threshold = 0.65
            below = sum(1 for v in vals if v < threshold)
            fig = build_confidence_figure(vals, threshold)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            st.caption(
                f"{below:,}/{len(vals):,} scored rows ({below/len(vals)*100:.0f}%) sit below the "
                f"configured {threshold} confidence threshold"
            )

    with col2:
        label_df = load_sentiment_label_breakdown()
        if label_df.empty:
            st.info("No scores yet.")
        else:
            order = ["positive", "neutral", "negative"]
            label_df = label_df.set_index("label").reindex(order).reset_index()
            label_df["c"] = label_df["c"].fillna(0).astype(int)
            label_df["avg_conf"] = label_df["avg_conf"].fillna(0.0)
            fig = build_sentiment_distribution_figure(
                labels=list(label_df["label"].fillna("unknown")),
                counts=list(label_df["c"]),
                avg_confs=list(label_df["avg_conf"]),
            )
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            st.caption("85%+ neutral is typical for a Q&A-heavy forum — but note the low "
                       "average confidence (~0.6) even within label.")


def _render_ticker_concentration() -> None:
    df, hhi = load_ticker_concentration(top_n=15)
    if df.empty:
        st.info("No scored tickers yet.")
        return

    df = df.sort_values("c", ascending=True)
    fig = build_ticker_concentration_figure(
        tickers=list(df["ticker"]),
        shares=list(df["pct"]),
        counts=list(df["c"]),
        hhi=hhi,
        n_total_tickers=len(df),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    concentration_label = (
        "unconcentrated" if hhi < 1500 else
        "moderately concentrated" if hhi < 2500 else
        "highly concentrated"
    )
    st.caption(
        f"Herfindahl-Hirschman Index = {hhi:.0f} / 10,000 — {concentration_label} "
        f"(US DOJ treats HHI < 1,500 as unconcentrated). Despite one singular lead, discussion "
        f"volume is genuinely spread across all 50 tracked tickers."
    )


def _render_scoring_cadence() -> None:
    df = load_scoring_cadence()
    if df.empty:
        st.info("No scoring data yet.")
        return
    fig = build_scoring_cadence_figure(
        dates=list(df["day"]),
        counts=list(df["c"]),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption(
        "Scoring runs in large batches rather than a steady trickle — a side-effect of "
        "the 3-hourly scrape-then-score pipeline on free-tier compute."
    )


def _render_engagement_scatter() -> None:
    df = load_engagement_scatter_data()
    corr = load_engagement_correlation()
    if df.empty or corr["n"] < 5:
        st.info("Not enough scored posts yet to compute engagement vs. sentiment.")
        return

    threshold = 0.65
    color_map = {"positive": _GREEN, "neutral": _SUBTLE, "negative": _RED}
    facets = [
        (f"confidence ≥ {threshold}", df[df["confidence"] >= threshold]),
        (f"confidence < {threshold}", df[df["confidence"] < threshold]),
    ]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                         subplot_titles=[f"{t}  (n={len(d):,})" for t, d in facets],
                         vertical_spacing=0.14)
    for row, (_, facet_df) in enumerate(facets, start=1):
        for label in ("neutral", "negative", "positive"):
            sub = facet_df[facet_df["label"] == label]
            fig.add_trace(
                go.Scatter(
                    x=sub["sentiment"], y=sub["replies"], mode="markers",
                    marker=dict(size=7, color=color_map[label], opacity=0.65),
                    name=label.capitalize(), legendgroup=label,
                    showlegend=(row == 1),
                    hovertemplate=f"<b>{label.capitalize()}</b><br>sentiment %{{x:.2f}}"
                                  f"<br>%{{y}} replies<extra></extra>",
                ),
                row=row, col=1,
            )
    fig.update_layout(
        plot_bgcolor=_PLOT_BG,
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color=_TEXT),
        margin=dict(l=0, r=12, t=8, b=8),
        height=480,
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right",
                    font=dict(size=10, color=_MUTED), bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(range=[-1.08, 1.08], gridcolor=_GRID,
                     tickfont=dict(size=10, color=_MUTED),
                     zeroline=True, zerolinecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, tickfont=dict(size=10, color=_MUTED), title=None)
    fig.update_xaxes(title=dict(text="Sentiment (−1 to +1)",
                                font=dict(size=10, color=_MUTED)), row=2, col=1)
    for ann in fig["layout"]["annotations"]:
        ann["font"] = dict(size=11.5, color=_TEXT)
        ann["x"] = 0
        ann["xanchor"] = "left"

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    c1, c2, c3 = st.columns(3)
    c1.metric("Scored pairs (n)", f"{corr['n']:,}")
    c2.metric("r(replies, sentiment)", f"{corr['r_sentiment']:+.3f}")
    c3.metric("r(replies, |sentiment|)", f"{corr['r_abs_sentiment']:+.3f}")
    st.caption(
        "Both correlations are indistinguishable from zero — reply count shows no relationship "
        "with sentiment direction or extremity, in either confidence facet."
    )


def _render_pipeline_documentation() -> None:
    """How-it-works documentation with live stats and clickable links."""

    # ── Live data ────────────────────────────────────────────────────────────
    f = load_pipeline_funnel()
    mm_df = load_match_method_breakdown()
    conf_df = load_confidence_values()

    total_links = int(mm_df["all_count"].sum()) if not mm_df.empty else 0
    fuzzy_row = mm_df[mm_df["method"] == "fuzzy"] if not mm_df.empty else mm_df
    fuzzy_pct = float(fuzzy_row["all_pct"].iloc[0]) if not fuzzy_row.empty else 0.0

    if not conf_df.empty:
        vals = list(conf_df["confidence"])
        scored_total = len(vals)
        below_thresh = sum(1 for v in vals if v < 0.65)
        below_pct = below_thresh / scored_total * 100
    else:
        vals, scored_total, below_thresh, below_pct = [], 0, 0, 0.0

    st.markdown('<a id="data-collection"></a>', unsafe_allow_html=True)
    st.markdown(
        f"""
**1. Data Collection**

[Pantip.com](https://pantip.com/tag/หุ้น) is a Thai web forum. Thai retail investors post there about SET-listed stocks — e.g. *"should I buy DELTA?"*, *"PTT is crashing!"*.

The scraper targets 5 investment tag pages using:

- **Selenium** — browser automation: opens an invisible Chrome window, navigates to 5 investment tag pages and scrolls through listings
- **BeautifulSoup** — Python HTML Scraper: extracts post ID, title, body text, timestamp, and reply count

Raw data lands in the `posts` table in [Turso](https://turso.tech), a cloud-hosted SQLite database, currently store **{f['scraped']:,} posts** across three tables:
- `posts` (raw text; title + body + reply count + timestamp),
- `post_tickers` ({total_links:,} rows — which post mentions which stock it belongs to), and
- `scores` ({f['scored']:,} rows — NLP output).
""",
        unsafe_allow_html=False,
    )

    st.markdown('<a id="preprocessing"></a>', unsafe_allow_html=True)
    st.markdown(
        f"""
**2. Preprocessing — Entity Matching**

A post about *"DELTA กำลังขึ้น"* needs to be linked to the ticker `DELTA`. The matcher tries four methods in order:
1) Exact ticker match — does the post contain the exact string "DELTA"?
2) Exact company name — does it contain the word "Delta Electronics"?
3) Alias dictionary — does it contain a known Thai nickname for the company?
4) Fuzzy match via [RapidFuzz](https://github.com/maxbachmann/RapidFuzz) `token_set_ratio` on [PyThaiNLP](https://github.com/PyThaiNLP/pythainlp) to find approximate matches (tokenised text with threshold ≥ 92.)

Method 4 requires aliases to be at least 8 characters and scores them using token_set_ratio on PyThaiNLP-segmented text, with a threshold of 92. These guards are necessary because Thai has no word spaces — without them, a short alias would match inside almost any long post body at high confidence, flooding the links table with noise. Currently fuzzy accounts for {fuzzy_pct:.0f}% of all {total_links:,} links.
""",
        unsafe_allow_html=False,
    )

    st.markdown('<a id="nlp-model"></a>', unsafe_allow_html=True)
    st.markdown(
        f"""
**3. NLP Model — Sentiment Scoring**

The NLP model is [cardiffnlp/twitter-xlm-roberta-base-sentiment](https://huggingface.co/cardiffnlp/twitter-xlm-roberta-base-sentiment) from HuggingFace.
XLM-RoBERTa is a transformer trained on 100 languages including Thai. The Cardiff fine-tune specialises it for social-media sentiment.

Inference: tokenise the post body → 12 attention layers → 3 output logits (positive / neutral / negative) → softmax → the winning class becomes the label, its probability becomes the confidence score

Only predictions with confidence ≥ 0.65 are stored — roughly 2× the random-chance baseline of 0.33 for a 3-class model. Results go into `scores`: label (positive / neutral / negative), sentiment (−1 to +1), confidence (0 to 1).
""",
        unsafe_allow_html=False,
    )

    above_thresh = scored_total - below_thresh
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Score rows", f"{scored_total:,}")
    k2.metric("Posts scored", f"{f['scored']:,}")
    k3.metric("Above threshold", f"{above_thresh:,}")
    k4.metric("Below threshold", f"{below_thresh:,}")

    st.markdown('<a id="downstream-usage"></a>', unsafe_allow_html=True)
    st.markdown(
        f"""
**4. Downstream Usage**

- **Alerts**  —  for each ticker, a Z-score measures how many standard deviations today's rolling sentiment is from the historical mean; |Z| > 0.65 fires an alert.

- **Backtest**  —  downloads historical prices from [yfinance](https://github.com/ranaroussi/yfinance) and computes Pearson r (via [SciPy](https://github.com/scipy/scipy)) between lagged sentiment and next-day price returns, asking whether yesterday's sentiment predicts today's move.

- **Kaggle Export**  —  the full dataset is uploaded to [Kaggle](https://www.kaggle.com/datasets/kyawswarheinm/pantip-set-sentiment) as a CSV every 3 hours via GitHub Actions.

- **Dashboard**  —  [Streamlit](https://streamlit.io) + [Plotly](https://plotly.com/python/) served on Streamlit Community Cloud, reading live data from [Turso](https://turso.tech) on every page load.
""",
        unsafe_allow_html=False,
    )

    st.markdown('<a id="gh-actions-workflows"></a>', unsafe_allow_html=True)
    st.markdown(
        """
**5. GitHub Actions**

Two workflows:
- `scrape.yml` — **Active**, runs every 3 hours — scrape → entity-match → NLP score → alerts → backtest (price refresh + lag correlation) → Kaggle export. (The full automated pipeline end-to-end)
- `kaggle_export.yml` — **Disabled**, serves as a standalone export trigger, useful for testing the Kaggle export step in isolation during development phase.
""",
        unsafe_allow_html=False,
    )


def _render_lag_correlation() -> None:
    tickers = load_tickers_with_prices()
    if not tickers:
        st.info(
            "No price data yet. Run `python -m backtest.correlation` to fetch prices "
            "from yfinance and populate the prices table."
        )
        return

    col_sel, col_btn = st.columns([4, 1])
    with col_sel:
        ticker = st.selectbox("Ticker", tickers, key="doc_backtest_ticker")
    with col_btn:
        st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
        if st.button("Refresh", key="lag_cache_clear", help="Force a fresh price fetch and recalculate now"):
            load_lag_correlation.clear()
            load_tickers_with_prices.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    df = load_lag_correlation(ticker)

    with st.expander("DEBUG — raw data frame from load_lag_correlation"):
        st.write(df)

    valid = df.dropna(subset=["pearson_r", "pearson_p"]) if not df.empty else df
    if valid.empty:
        stats = load_sentiment_date_stats(ticker)
        ud = stats["unique_days"]
        n_max = int(df["n_obs"].max()) if not df.empty else 0
        if n_max >= 5:
            st.info(
                f"**{ticker}** has {n_max} overlapping days but sentiment is constant across all of them "
                f"(all posts predicted the same label) — correlation is undefined. "
                "More sentiment variation is needed across different days."
            )
        else:
            st.info(
                f"**{ticker}** has **{ud} unique posting day{'s' if ud != 1 else ''}** "
                f"({stats['min_day']} → {stats['max_day']}) but only {n_max} overlap with price data. "
                "Correlation needs ≥ 5 overlapping days. "
                "Run `python -m backtest.correlation` to fetch prices for the full date range."
            )
        return

    fig = build_lag_correlation_figure(valid, ticker)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    best = valid.loc[valid["pearson_r"].abs().idxmax()]
    sig = "p < 0.05 — statistically significant" if best["pearson_p"] < 0.05 else f"p = {best['pearson_p']:.2f} — not significant"
    st.caption(
        f"Strongest signal at lag {int(best['lag'])}d "
        f"(r = {best['pearson_r']:+.3f}, {sig}, n = {int(best['n_obs'])} days). "
        "Positive r at lag > 0 means today's sentiment tends to predict price movement n days later. "
        "Blue bars = p < 0.05."
    )


def _render_qa() -> None:
    pass


def render_documentation_tab() -> None:
    _render_toc()

    _section_label("Data Flow Diagram — Automated Pipeline", anchor="data-flow")
    _render_data_flow_diagram()

    _section_label("How the Automation works", anchor="how-it-works")
    _render_pipeline_documentation()

    _section_label("Automation pipeline — GitHub Actions", anchor="github-actions")
    _render_automation_pipeline()

    st.markdown('<a id="tools-stack"></a>', unsafe_allow_html=True)
    st.markdown(
        """
**Tools & Services Used**

- *[Pantip.com](https://pantip.com/tag/หุ้น)* as **Data Source** (5 Thai investment tag pages scraped for posts)
- *[Selenium](https://www.selenium.dev/) + [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)* as **Scraping Tools** (Browser automation and HTML extraction)
- *[PyThaiNLP](https://github.com/PyThaiNLP/pythainlp) + [RapidFuzz](https://github.com/maxbachmann/RapidFuzz)* as **Entity Matching** (Thai text tokenization and fuzzy ticker linking)
- *[HuggingFace Transformers](https://huggingface.co/cardiffnlp/twitter-xlm-roberta-base-sentiment) (XLM-RoBERTa)* as **NLP Model** (Multilingual sentiment inference)
- *[yfinance](https://github.com/ranaroussi/yfinance)* as **Price Data** (Historical SET stock prices from Yahoo Finance)
- *[SciPy](https://scipy.org/)* as **Backtest** (Pearson r and p-value for lag correlation)
- *[NumPy](https://numpy.org/)* as **Alerts** (Z-score spike detection)
- *[Turso](https://turso.tech) (LibSQL / SQLite)* as **Database** (Cloud-hosted storage for posts, scores, prices, and alerts)
- *[GitHub Actions](https://github.com/kyawswarheinm/Pantip-Sentiment/actions)* as **Automation** (3-hourly pipeline on free-tier runners)
- *[Kaggle](https://www.kaggle.com/datasets/kyawswarheinm/pantip-set-sentiment)* API as **Dataset Export** (Public CSV dataset refreshed every 3 hours)
- *[Streamlit](https://streamlit.io) + [Plotly](https://plotly.com/python/)* as **Dashboard** (Read-only app served on [Streamlit Community Cloud](https://streamlit.io/cloud))

Full write-up, problems encountered, and methodology in [the project README](https://github.com/kyawswarheinm/pantip-sentiment#readme).

‎

---
""",
        unsafe_allow_html=False,
    )

    _section_label("Post-to-score conversion funnel", anchor="funnel")
    _render_funnel_detail()

    st.markdown(
        """
    - Not all scraped posts contain text or mention a tracked stock.
    - Posts that mention a tracked stock produce a ticker link — only linked posts are eligible for scoring.
    - Only predictions with confidence ≥ 0.65 are stored; lower-confidence outputs are discarded.

    ‎

    """,
        unsafe_allow_html=False,
    )

    _section_label("Entity-matching quality: all links vs. what got scored", anchor="entity-matching")
    _render_match_method()

    st.markdown(
        """
The chart compares method breakdown for all ticker links vs. only those that made it through NLP scoring.

Three methods link a post to a ticker: 1) exact symbol or company name, 2) alias dictionary, 3) approximate fuzzy match via RapidFuzz

Fuzzy is intentionally a small share because  — 
- aliases shorter than 8 characters are skipped, 
- the threshold is 92 out of 100, and 
- token_set_ratio prevents short substring coincidences from scoring high.

‎

""",
        unsafe_allow_html=False,
    )

    _section_label("Model confidence & sentiment distribution", anchor="model-confidence")
    _render_confidence_and_labels()

    st.markdown(
        """
- **Confidence Histogram**: scores across all scored post-ticker pairs.
- **Sentiment Label Distribution**: breakdown by predicted label. A large neutral majority is expected for a Q&A forum where most posts ask questions rather than express strong opinions.
- Low average confidence within each label reflects genuine ambiguity in short, informal Thai text.

‎

""",
        unsafe_allow_html=False,
    )

    _section_label("Ticker concentration", anchor="ticker-concentration")
    _render_ticker_concentration()

    st.markdown(
        """
- Each bar shows one ticker's share of total scored post-ticker pairs (top 15 shown).
- The Herfindahl-Hirschman Index (HHI) measures how concentrated discussion is — 0 means perfectly spread, 10,000 means one ticker takes everything.
- The HHI sits below 1,500 (the US DOJ threshold for unconcentrated markets), meaning discussion is genuinely spread across all tracked stocks.

‎

---
""",
        unsafe_allow_html=False,
    )



#     _section_label("Scoring cadence")
#     _render_scoring_cadence()

#     st.markdown(
#         """
# - Each bar shows how many scores were written on that day.
# - The bursty pattern reflects the 3-hourly scrape-then-score pipeline — all posts from a scrape run are scored in one batch.
# - Gaps between bursts are periods when the GitHub Actions runner was idle or no new posts arrived.

# ‎

# """,
#         unsafe_allow_html=False,
#     )






    _section_label("MAIN QUESTION: Does sentiment predict price? (Lag correlation backtest)", anchor="lag-correlation")
    _render_lag_correlation()

    st.markdown(
        """
- Pearson r (and Spearman r) are used for this analysis.
- Pearson r measures linear correlation between two variables — here, daily mean sentiment and stock price return. (Ranges from −1 to +1;)
- A Lag answers the question: "Does sentiment from N days ago predict today's price?" (Lag 0 = same day. Lag 1 = sentiment today vs. price tomorrow. Lag 2 = two days later, and so on.)
- Blue bars => statistically significant (p < 0.05); 
- Grey bars => could be noise;
- A meaningful positive bar at lag 1–2 would suggest sentiment leads price — the core hypothesis of this project.

A few notices about the backtest:
- n=37 days is very small for a correlation study. Finance typically wants 200+ days for meaningful conclusions.
- Correlation ≠ causation. The model can't tell if sentiment really causes price moves.
- p < 0.05 with n=37 is a weak standard. With 6 bars tested simultaneously, there's a ~27% chance at least one bar appears significant purely by chance (= 1 − 0.95⁶).

‎

""",
        unsafe_allow_html=False,
    )

    _section_label("ADDITIONAL QUESTION: Does engagement correlate with sentiment?", anchor="engagement")
    _render_engagement_scatter()

    st.markdown(
        """
- Reply count on Pantip reflects curiosity or controversy, and thus, is considered as ENGAGEMENT. Since it is not necessarily sentiment direction, a weak or near-zero correlation is expected.
- Each dot stands for one post that has a sentiment score; x-axis is sentiment score (−1 to +1), y-axis is reply count (engagement).
- The Scatter chart is split by confidence level to show whether the relationship holds for high-confidence predictions separately.

‎

---
""",
        unsafe_allow_html=False,
    )

    _section_label("Known limitations", anchor="limitations")
    st.markdown(
        """
- **Some posts have a NULL `posted_at`** because Pantip's SSR datetime parser occasionally fails. Time-series charts use `posted_at` where available and fall back to `scored_at` otherwise — so a small fraction of posts may cluster around the pipeline run date rather than when they were actually written.
- **Reply counts are sourced inconsistently** — the live scraper uses fast heuristic HTML parsing; the backfill scripts use Pantip's accurate AJAX endpoint.
- **The Thai alias dictionary covers ~50 names by hand** — tickers outside that list rely on exact-symbol or fuzzy matching with no alias safety net.
- **No human-labeled ground truth** — model accuracy relies on the pre-trained XLM-RoBERTa checkpoint; no Thai financial-sentiment ground truth exists to evaluate against.
        """,
        unsafe_allow_html=False,
    )

    _section_label("Project Attribution", anchor="contributors")
    st.markdown(
        """
- **[Kyaw Swar Hein](https://github.com/kyawswarheinm) (Project Owner & Sole Developer)** : Conceived, designed, and built the project end-to-end. Responsible for the original research question, system architecture, technical design, feature planning and prioritization, implementation, debugging, testing strategy, code review, deployment, documentation review, and all engineering decisions. All project direction, analysis, problem-solving, and final implementation decisions were made by the project owner.

- **[Claude](https://github.com/claude) (Anthropic; AI Development Assistant)** : Provided AI-assisted support for selected implementation tasks under the project owner's direction, including generating ***boilerplate code***, assisting with repetitive refactoring, helping with research/documentation, and accelerating routine development tasks.

""",
        unsafe_allow_html=False,
    )

    _section_label("Research Paper", anchor="research_paper")
    st.markdown(
        """
// A research paper is currently being prepared based on the findings of this project. The study will investigate the relationship between social media sentiment and actual stock price movements, solely focusing on the Thai stock market.

// Currently, waiting for more data to accumulate before the research paper can be written.

        """,
        unsafe_allow_html=False,
    )
