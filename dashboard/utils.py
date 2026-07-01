"""Shared DB query helpers for the Streamlit dashboard."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
CACHE_TTL: int = int(os.getenv("STREAMLIT_CACHE_TTL", "900"))


@st.cache_data(ttl=CACHE_TTL)
def load_tickers() -> list[str]:
    from db.client import db_session
    with db_session() as db:
        rows = db.fetchall("SELECT ticker FROM tickers ORDER BY ticker")
    return [r["ticker"] for r in rows]


@st.cache_data(ttl=CACHE_TTL)
def load_active_tickers() -> list[str]:
    """Tickers that have at least one scored post — used as the dashboard default."""
    from db.client import db_session
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT DISTINCT pt.ticker
            FROM post_tickers pt
            JOIN scores s ON s.post_ticker_id = pt.id
            ORDER BY pt.ticker
            """
        )
    return [r["ticker"] for r in rows]


@st.cache_data(ttl=CACHE_TTL)
def load_sentiment_rankings(start: str, end: str) -> pd.DataFrame:
    """All tickers with scores in the date range, ranked by avg sentiment."""
    from db.client import db_session
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT pt.ticker,
                   ROUND(AVG(s.sentiment), 3)     AS avg_sentiment,
                   COUNT(DISTINCT pt.post_id)      AS post_count
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            WHERE date(s.scored_at) BETWEEN ? AND ?
            GROUP BY pt.ticker
            ORDER BY avg_sentiment DESC
            """,
            (start, end),
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL)
def load_volume_timeseries(start: str, end: str) -> pd.DataFrame:
    """Daily scored-post count for the activity sparkline."""
    from db.client import db_session
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT date(s.scored_at) AS day,
                   COUNT(DISTINCT s.post_ticker_id) AS post_count
            FROM scores s
            WHERE date(s.scored_at) BETWEEN ? AND ?
            GROUP BY day
            ORDER BY day
            """,
            (start, end),
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


@st.cache_data(ttl=CACHE_TTL)
def load_sentiment_timeseries(
    tickers: tuple[str, ...],
    start: str,
    end: str,
    window_days: int,
) -> pd.DataFrame:
    """Return daily mean sentiment per ticker, rolling-averaged over `window_days`."""
    from db.client import db_session

    if not tickers:
        return pd.DataFrame()

    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT date(s.scored_at) AS day,
                   pt.ticker,
                   AVG(s.sentiment) AS mean_sentiment,
                   COUNT(*) AS post_count
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            WHERE pt.ticker IN ({placeholders})
              AND date(s.scored_at) BETWEEN ? AND ?
            GROUP BY day, pt.ticker
            ORDER BY day
            """,
            (*tickers, start, end),
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Keep as plain date objects to avoid midnight-timestamp display bug
    df["day"] = pd.to_datetime(df["day"]).dt.date
    df = df.pivot(index="day", columns="ticker", values="mean_sentiment")
    df.columns.name = None
    df = df.rolling(window=window_days, min_periods=1).mean()
    return df


@st.cache_data(ttl=CACHE_TTL)
def load_prices(tickers: tuple[str, ...], start: str, end: str) -> pd.DataFrame:
    from db.client import db_session

    if not tickers:
        return pd.DataFrame()

    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT trade_date, ticker, close_adj
            FROM prices
            WHERE ticker IN ({placeholders})
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (*tickers, start, end),
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df.columns.name = None
    return df.pivot(index="trade_date", columns="ticker", values="close_adj")


@st.cache_data(ttl=CACHE_TTL)
def load_recent_posts(tickers: tuple[str, ...], start: str, end: str, limit: int = 100) -> pd.DataFrame:
    """
    Posts feed filtered by scored_at date range (not posted_at, which is often NULL
    when Pantip's datetime HTML fails to parse).
    """
    from db.client import db_session

    if not tickers:
        return pd.DataFrame()

    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT p.post_id,
                   p.title_th,
                   p.url,
                   pt.ticker,
                   s.label,
                   ROUND(s.sentiment, 3) AS sentiment,
                   ROUND(s.confidence, 3) AS confidence,
                   p.replies,
                   COALESCE(p.posted_at, s.scored_at) AS posted_at
            FROM posts p
            JOIN post_tickers pt ON pt.post_id = p.post_id
            JOIN scores s ON s.post_ticker_id = pt.id
            WHERE pt.ticker IN ({placeholders})
              AND date(s.scored_at) BETWEEN ? AND ?
            ORDER BY s.scored_at DESC
            LIMIT ?
            """,
            (*tickers, start, end, limit),
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL)
def load_alerts(tickers: tuple[str, ...]) -> pd.DataFrame:
    from db.client import db_session

    if not tickers:
        return pd.DataFrame()

    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT ticker, rule_type, trigger_value, threshold_used,
                   fired_at, resolved
            FROM alerts
            WHERE ticker IN ({placeholders})
            ORDER BY fired_at DESC
            LIMIT 50
            """,
            tickers,
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL)
def load_summary_metrics(tickers: tuple[str, ...], start: str, end: str) -> dict:
    """
    Summary cards — uses scored_at for date filtering since posted_at is often NULL.
    """
    from db.client import db_session

    if not tickers:
        return {"total_posts": 0, "avg_sentiment": 0.0, "open_alerts": 0, "tickers_tracked": 0}

    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        post_row = db.fetchall(
            f"""
            SELECT COUNT(DISTINCT p.post_id) AS cnt, AVG(s.sentiment) AS avg_sent
            FROM posts p
            JOIN post_tickers pt ON pt.post_id = p.post_id
            JOIN scores s ON s.post_ticker_id = pt.id
            WHERE pt.ticker IN ({placeholders})
              AND date(s.scored_at) BETWEEN ? AND ?
            """,
            (*tickers, start, end),
        )
        alert_row = db.fetchall(
            f"""
            SELECT COUNT(*) AS cnt FROM alerts
            WHERE ticker IN ({placeholders}) AND resolved = 0
            """,
            tickers,
        )

    return {
        "total_posts": post_row[0]["cnt"] if post_row else 0,
        "avg_sentiment": round(float(post_row[0]["avg_sent"] or 0.0), 3) if post_row else 0.0,
        "open_alerts": alert_row[0]["cnt"] if alert_row else 0,
        "tickers_tracked": len(tickers),
    }


# ---------------------------------------------------------------------------
# Documentation & Analysis tab — live versions of the README's charts
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def load_pipeline_funnel() -> dict:
    """Scraped → linked-to-ticker → scored post counts (whole-history, no date filter)."""
    from db.client import db_session

    with db_session() as db:
        scraped = db.fetchall("SELECT COUNT(*) c FROM posts")[0]["c"]
        linked = db.fetchall(
            "SELECT COUNT(DISTINCT post_id) c FROM post_tickers"
        )[0]["c"]
        scored = db.fetchall(
            "SELECT COUNT(DISTINCT pt.post_id) c FROM post_tickers pt "
            "JOIN scores s ON s.post_ticker_id = pt.id"
        )[0]["c"]
        scored_rows = db.fetchall("SELECT COUNT(*) c FROM scores")[0]["c"]
        alerts_total = db.fetchall("SELECT COUNT(*) c FROM alerts")[0]["c"]
        tickers_total = db.fetchall("SELECT COUNT(*) c FROM tickers")[0]["c"]

    return {
        "scraped": scraped,
        "linked": linked,
        "scored": scored,
        "scored_rows": scored_rows,
        "alerts_total": alerts_total,
        "tickers_total": tickers_total,
    }


@st.cache_data(ttl=CACHE_TTL)
def load_match_method_breakdown() -> pd.DataFrame:
    """Match-method composition for all ticker links vs. the scored subset."""
    from db.client import db_session

    with db_session() as db:
        all_rows = db.fetchall(
            "SELECT match_method, COUNT(*) c FROM post_tickers GROUP BY match_method"
        )
        scored_rows = db.fetchall(
            "SELECT pt.match_method, COUNT(*) c FROM post_tickers pt "
            "JOIN scores s ON s.post_ticker_id = pt.id GROUP BY pt.match_method"
        )

    all_map = {r["match_method"]: r["c"] for r in all_rows}
    scored_map = {r["match_method"]: r["c"] for r in scored_rows}
    all_total = sum(all_map.values()) or 1
    scored_total = sum(scored_map.values()) or 1

    records = []
    for method in ("exact", "alias", "fuzzy"):
        records.append({
            "method": method,
            "all_pct": all_map.get(method, 0) / all_total * 100,
            "all_count": all_map.get(method, 0),
            "scored_pct": scored_map.get(method, 0) / scored_total * 100,
            "scored_count": scored_map.get(method, 0),
        })
    return pd.DataFrame(records)


@st.cache_data(ttl=CACHE_TTL)
def load_confidence_values() -> pd.DataFrame:
    """Raw confidence values for every scored row — for the threshold histogram."""
    from db.client import db_session

    with db_session() as db:
        rows = db.fetchall("SELECT confidence FROM scores")
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL)
def load_ticker_concentration(top_n: int = 15) -> tuple[pd.DataFrame, float]:
    """Top-N tickers by scored post count, plus the Herfindahl-Hirschman Index (0-10,000)."""
    from db.client import db_session

    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT pt.ticker, COUNT(DISTINCT pt.post_id) c
            FROM post_tickers pt JOIN scores s ON s.post_ticker_id = pt.id
            GROUP BY pt.ticker ORDER BY c DESC
            """
        )
    if not rows:
        return pd.DataFrame(), 0.0

    total = sum(r["c"] for r in rows)
    hhi = sum((r["c"] / total) ** 2 for r in rows) * 10000
    df = pd.DataFrame(rows[:top_n])
    df["pct"] = df["c"] / total * 100
    return df, round(hhi, 0)


@st.cache_data(ttl=CACHE_TTL)
def load_sentiment_label_breakdown() -> pd.DataFrame:
    """Label counts + mean confidence per label, for the sentiment-distribution chart."""
    from db.client import db_session

    with db_session() as db:
        rows = db.fetchall(
            "SELECT label, COUNT(*) c, AVG(confidence) avg_conf FROM scores GROUP BY label"
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL)
def load_scoring_cadence() -> pd.DataFrame:
    """Scored-row count per day — reveals batch-y vs. steady-state scoring runs."""
    from db.client import db_session

    with db_session() as db:
        rows = db.fetchall(
            "SELECT date(scored_at) AS day, COUNT(*) AS c FROM scores GROUP BY day ORDER BY day"
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL)
def load_engagement_correlation() -> dict:
    """Pearson r between replies and (sentiment, |sentiment|) on the scored set."""
    from db.client import db_session

    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT p.replies, s.sentiment
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            """
        )
    if len(rows) < 5:
        return {"n": len(rows), "r_sentiment": None, "r_abs_sentiment": None}

    df = pd.DataFrame(rows)
    df["replies"] = df["replies"].fillna(0)
    df["abs_sentiment"] = df["sentiment"].abs()
    return {
        "n": len(df),
        "r_sentiment": round(float(df["replies"].corr(df["sentiment"])), 3),
        "r_abs_sentiment": round(float(df["replies"].corr(df["abs_sentiment"])), 3),
    }


@st.cache_data(ttl=CACHE_TTL)
def load_sentiment_date_stats(ticker: str) -> dict:
    """Unique scoring days and date range for a ticker — used to diagnose sparse backtest data."""
    from db.client import db_session
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT MIN(date(COALESCE(p.posted_at, s.scored_at))) AS min_day,
                   MAX(date(COALESCE(p.posted_at, s.scored_at))) AS max_day,
                   COUNT(DISTINCT date(COALESCE(p.posted_at, s.scored_at))) AS unique_days
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            WHERE pt.ticker = ?
            """,
            (ticker,),
        )
    if not rows or not rows[0]["min_day"]:
        return {"unique_days": 0, "min_day": None, "max_day": None}
    return dict(rows[0])


@st.cache_data(ttl=CACHE_TTL)
def load_tickers_with_prices() -> list[str]:
    """Tickers that have at least one row in the prices table, sorted by score count."""
    from db.client import db_session
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT pr.ticker, COUNT(s.post_ticker_id) AS score_count
            FROM prices pr
            LEFT JOIN post_tickers pt ON pt.ticker = pr.ticker
            LEFT JOIN scores s ON s.post_ticker_id = pt.id
            GROUP BY pr.ticker
            ORDER BY score_count DESC, pr.ticker
            """
        )
    return [r["ticker"] for r in rows]


@st.cache_data(ttl=CACHE_TTL)
def load_lag_correlation(ticker: str) -> pd.DataFrame:
    """Pearson/Spearman r at lags 0–5 between daily sentiment and price return.

    Automatically fetches missing price data from yfinance on cache miss so the
    dashboard stays current without a manual backtest run. Only downloads days
    newer than the latest stored price row (incremental top-up).
    """
    from datetime import date as _date, timedelta
    from backtest.correlation import compute_lag_correlation, fetch_and_store_prices, MAX_LAG
    from db.client import db_session

    today = _date.today()

    with db_session() as db:
        price_row = db.fetchall(
            "SELECT MIN(trade_date) AS min_d, MAX(trade_date) AS max_d FROM prices WHERE ticker = ?",
            (ticker,),
        )
        sent_row = db.fetchall(
            """
            SELECT MIN(date(COALESCE(p.posted_at, s.scored_at))) AS min_day,
                   MAX(date(COALESCE(p.posted_at, s.scored_at))) AS max_day
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            WHERE pt.ticker = ?
            """,
            (ticker,),
        )

    if not sent_row or not sent_row[0]["min_day"]:
        return pd.DataFrame()

    price_max = price_row[0]["max_d"] if price_row and price_row[0]["max_d"] else None

    if price_max is None:
        # No prices at all — fetch from earliest sentiment date
        fetch_start = _date.fromisoformat(sent_row[0]["min_day"])
    elif _date.fromisoformat(price_max) < today:
        # Prices exist but stale — top up from day after latest stored row
        fetch_start = _date.fromisoformat(price_max) + timedelta(days=1)
    else:
        fetch_start = None  # Already up to date

    if fetch_start is not None:
        fetch_and_store_prices(ticker, fetch_start, today + timedelta(days=MAX_LAG + 7))

    start = _date.fromisoformat(sent_row[0]["min_day"])
    end   = _date.fromisoformat(sent_row[0]["max_day"])
    return compute_lag_correlation(ticker, start=start, end=end)


@st.cache_data(ttl=CACHE_TTL)
def load_engagement_scatter_data() -> pd.DataFrame:
    """Raw (replies, sentiment, confidence, label) rows for the engagement scatter plot."""
    from db.client import db_session

    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT p.replies, s.sentiment, s.confidence, s.label
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            """
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["replies"] = df["replies"].fillna(0)
    return df
