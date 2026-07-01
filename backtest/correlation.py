"""
Lag correlation analysis: daily sentiment vs stock price returns.

Computes Pearson and Spearman r between daily mean sentiment and return_1d
at lags 0–5 trading days for a given ticker and date range.
Also fetches price history from yfinance if not already in the DB.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from db.client import db_session

logger = logging.getLogger(__name__)

MAX_LAG = 5


# ---------------------------------------------------------------------------
# Price data helpers
# ---------------------------------------------------------------------------

def _yf_symbol(ticker: str) -> str:
    """Convert SET ticker to yfinance format (e.g. 'PTT' → 'PTT.BK')."""
    return f"{ticker}.BK"


def fetch_and_store_prices(
    ticker: str,
    start: date,
    end: date,
) -> int:
    """
    Download daily OHLCV from yfinance and upsert into the `prices` table.
    Returns number of rows upserted.
    """
    symbol = _yf_symbol(ticker)
    try:
        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        logger.error("yfinance download failed for %s: %s", symbol, exc)
        return 0

    if df.empty:
        logger.warning("No price data from yfinance for %s", symbol)
        return 0

    df = df[["Close", "Volume"]].copy()
    df.columns = ["close_adj", "volume"]
    df.index = pd.to_datetime(df.index).date
    df = df.sort_index()
    df["return_1d"] = np.log(df["close_adj"] / df["close_adj"].shift(1))

    rows = [
        (
            ticker,
            str(idx),
            float(row["close_adj"]) if not np.isnan(row["close_adj"]) else None,
            float(row["volume"]) if not np.isnan(row["volume"]) else None,
            float(row["return_1d"]) if not np.isnan(row["return_1d"]) else None,
        )
        for idx, row in df.iterrows()
    ]

    sql = """
        INSERT INTO prices (ticker, trade_date, close_adj, volume, return_1d)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker, trade_date) DO UPDATE SET
            close_adj  = excluded.close_adj,
            volume     = excluded.volume,
            return_1d  = excluded.return_1d
    """
    with db_session() as db:
        db.executemany(sql, rows)

    logger.info("Upserted %d price rows for %s", len(rows), ticker)
    return len(rows)


# ---------------------------------------------------------------------------
# Sentiment aggregation
# ---------------------------------------------------------------------------

def _load_daily_sentiment(ticker: str, start: date, end: date) -> pd.Series:
    """Return a date-indexed Series of mean daily sentiment for `ticker`.

    Groups by posted_at (when the post was written), falling back to scored_at
    for the ~43 posts with NULL posted_at. This spreads sentiment across the
    original publishing dates rather than the batch-scoring dates.
    """
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT date(COALESCE(p.posted_at, s.scored_at)) AS day,
                   AVG(s.sentiment) AS mean_sentiment
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            WHERE pt.ticker = ?
              AND date(COALESCE(p.posted_at, s.scored_at)) BETWEEN ? AND ?
            GROUP BY day
            ORDER BY day
            """,
            (ticker, start.isoformat(), end.isoformat()),
        )
    if not rows:
        return pd.Series(dtype=float)

    idx = pd.to_datetime([r["day"] for r in rows]).date
    vals = [r["mean_sentiment"] for r in rows]
    return pd.Series(vals, index=idx, name="sentiment")


def _load_daily_returns(ticker: str, start: date, end: date) -> pd.Series:
    """Return a date-indexed Series of return_1d for `ticker`."""
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT trade_date, return_1d
            FROM prices
            WHERE ticker = ? AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (ticker, start.isoformat(), end.isoformat()),
        )
    if not rows:
        return pd.Series(dtype=float)

    idx = [date.fromisoformat(r["trade_date"]) for r in rows]
    vals = [r["return_1d"] for r in rows]
    return pd.Series(vals, index=idx, name="return_1d")


# ---------------------------------------------------------------------------
# Lag correlation
# ---------------------------------------------------------------------------

def compute_lag_correlation(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> pd.DataFrame:
    """
    Compute Pearson and Spearman r between daily mean sentiment and price
    return_1d at lags 0–5 trading days.

    Positive lag means sentiment leads price (sentiment at t predicts price at t+lag).

    Returns DataFrame with columns:
      lag, pearson_r, pearson_p, spearman_r, spearman_p, n_obs
    """
    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=180)

    # Extend end a little for lag window
    price_end = end + timedelta(days=MAX_LAG + 7)

    sentiment = _load_daily_sentiment(ticker, start, end)
    returns = _load_daily_returns(ticker, start, price_end)

    if sentiment.empty or returns.empty:
        logger.warning("Insufficient data for %s correlation", ticker)
        return pd.DataFrame(
            columns=["lag", "pearson_r", "pearson_p", "spearman_r", "spearman_p", "n_obs"]
        )

    results = []
    for lag in range(MAX_LAG + 1):
        # Align: sentiment[t] vs returns[t + lag]
        if lag == 0:
            returns_shifted = returns
        else:
            returns_shifted = returns.shift(-lag)  # shift index forward by lag

        combined = pd.DataFrame(
            {"sentiment": sentiment, "return": returns_shifted}
        ).dropna()

        n = len(combined)
        if n < 5:
            results.append(
                {"lag": lag, "pearson_r": None, "pearson_p": None,
                 "spearman_r": None, "spearman_p": None, "n_obs": n}
            )
            continue

        if combined["sentiment"].std() == 0 or combined["return"].std() == 0:
            results.append(
                {"lag": lag, "pearson_r": None, "pearson_p": None,
                 "spearman_r": None, "spearman_p": None, "n_obs": n}
            )
            continue

        pearson_r, pearson_p = stats.pearsonr(combined["sentiment"], combined["return"])
        spearman_r, spearman_p = stats.spearmanr(combined["sentiment"], combined["return"])

        results.append({
            "lag": lag,
            "pearson_r": round(float(pearson_r), 4),
            "pearson_p": round(float(pearson_p), 4),
            "spearman_r": round(float(spearman_r), 4),
            "spearman_p": round(float(spearman_p), 4),
            "n_obs": n,
        })

    df = pd.DataFrame(results)
    logger.info("Correlation for %s:\n%s", ticker, df.to_string(index=False))
    return df


def run_backtest(
    tickers: Optional[list[str]] = None,
    days: int = 180,
) -> dict[str, pd.DataFrame]:
    """
    Run lag correlation for a list of tickers (defaults to all tickers in DB).
    Also fetches fresh price data for each ticker before analysis.
    Returns {ticker: correlation_dataframe}.
    """
    end = date.today()
    default_start = end - timedelta(days=days)

    # Extend back to the earliest posted_at date so prices cover all sentiment data
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT MIN(date(COALESCE(p.posted_at, s.scored_at))) AS min_day
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            """
        )
    earliest_str = rows[0]["min_day"] if rows and rows[0]["min_day"] else None
    earliest = date.fromisoformat(earliest_str) if earliest_str else default_start
    start = min(earliest, default_start)

    if tickers is None:
        with db_session() as db:
            rows = db.fetchall("SELECT ticker FROM tickers ORDER BY ticker")
        tickers = [r["ticker"] for r in rows]

    results: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        logger.info("Processing %s", ticker)
        fetch_and_store_prices(ticker, start, end + timedelta(days=MAX_LAG + 7))
        df = compute_lag_correlation(ticker, start, end)
        if not df.empty:
            results[ticker] = df

    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    tickers_arg = sys.argv[1:] if len(sys.argv) > 1 else None
    run_backtest(tickers=tickers_arg)
