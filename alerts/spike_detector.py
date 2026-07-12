"""
Crisis alert engine: Z-score and volume-surge detection per ticker.

Rules:
  - zscore: rolling negative-sentiment Z-score ≥ ZSCORE_THRESHOLD over LOOKBACK_DAYS
  - volume_surge: today's post count > VOLUME_SURGE_MULTIPLIER × 7-day average

Uses 3 bulk queries across all tickers rather than per-ticker connections.
Alerts are deduplicated — no re-fire while an unresolved alert exists.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from dotenv import load_dotenv

from db.client import db_session

load_dotenv()
logger = logging.getLogger(__name__)

ZSCORE_THRESHOLD: float = float(os.getenv("ZSCORE_THRESHOLD", "2.5"))
VOLUME_SURGE_MULT: float = float(os.getenv("VOLUME_SURGE_MULTIPLIER", "3.0"))
LOOKBACK_DAYS: int = int(os.getenv("LOOKBACK_DAYS_ALERT", "7"))


# ---------------------------------------------------------------------------
# Bulk data fetchers (all tickers in one query each)
# ---------------------------------------------------------------------------

def _fetch_all_daily_neg_ratios(tickers: list[str]) -> dict[str, list[float]]:
    """
    Return {ticker: [daily_negative_ratio, ...]} ordered oldest-to-newest
    for the past LOOKBACK_DAYS days.
    """
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT pt.ticker,
                   date(s.scored_at) AS day,
                   COUNT(*) AS total,
                   SUM(CASE WHEN s.label = 'negative' THEN 1 ELSE 0 END) AS negative_count
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            WHERE pt.ticker IN ({placeholders})
              AND s.scored_at >= ?
            GROUP BY pt.ticker, day
            ORDER BY pt.ticker, day
            """,
            (*tickers, cutoff),
        )

    result: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        ratio = row["negative_count"] / row["total"] if row["total"] > 0 else 0.0
        result[row["ticker"]].append(ratio)
    return dict(result)


def _fetch_all_post_counts(tickers: list[str]) -> dict[str, tuple[int, float]]:
    """
    Return {ticker: (today_count, seven_day_avg)} for all tickers in one query.
    """
    today = datetime.utcnow().date().isoformat()
    week_ago = (datetime.utcnow() - timedelta(days=7)).date().isoformat()
    placeholders = ",".join("?" * len(tickers))

    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT pt.ticker,
                   date(p.posted_at) AS day,
                   COUNT(*) AS cnt
            FROM post_tickers pt
            JOIN posts p ON p.post_id = pt.post_id
            WHERE pt.ticker IN ({placeholders})
              AND date(p.posted_at) BETWEEN ? AND ?
            GROUP BY pt.ticker, day
            ORDER BY pt.ticker, day
            """,
            (*tickers, week_ago, today),
        )

    # Aggregate per ticker
    by_ticker: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        by_ticker[row["ticker"]][row["day"]] = row["cnt"]

    result: dict[str, tuple[int, float]] = {}
    for ticker in tickers:
        days = by_ticker.get(ticker, {})
        today_count = days.get(today, 0)
        all_counts = list(days.values())
        avg = float(np.mean(all_counts)) if all_counts else 0.0
        result[ticker] = (today_count, avg)
    return result


def _fetch_open_alerts(tickers: list[str]) -> set[tuple[str, str]]:
    """Return set of (ticker, rule_type) pairs with unresolved alerts."""
    placeholders = ",".join("?" * len(tickers))
    with db_session() as db:
        rows = db.fetchall(
            f"""
            SELECT ticker, rule_type FROM alerts
            WHERE ticker IN ({placeholders}) AND resolved = 0
            """,
            tickers,
        )
    return {(r["ticker"], r["rule_type"]) for r in rows}


def _fire_alerts(to_fire: list[tuple[str, str, float, float]]) -> None:
    """Bulk-insert new alert rows: [(ticker, rule_type, trigger_value, threshold), ...]"""
    if not to_fire:
        return
    try:
        with db_session() as db:
            db.executemany(
                """
                INSERT INTO alerts (ticker, rule_type, trigger_value, threshold_used)
                VALUES (?, ?, ?, ?)
                """,
                to_fire,
            )
        for ticker, rule, val, thresh in to_fire:
            logger.warning(
                "ALERT fired — ticker=%s rule=%s trigger=%.3f threshold=%.3f",
                ticker, rule, val, thresh,
            )
    except RuntimeError as exc:
        if "writes are blocked" in str(exc) or "forbidden" in str(exc).lower():
            logger.warning("Turso write limit reached — %d alerts computed but not stored", len(to_fire))
            return
        raise


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_all_checks() -> dict[str, list[str]]:
    """
    Run Z-score and volume-surge checks for every scored ticker.
    Uses 3 bulk DB queries total regardless of ticker count.
    Returns {ticker: [fired_rule_types]}.
    """
    with db_session() as db:
        rows = db.fetchall(
            "SELECT DISTINCT pt.ticker FROM post_tickers pt JOIN scores s ON s.post_ticker_id = pt.id"
        )
    tickers = [r["ticker"] for r in rows]
    if not tickers:
        logger.info("No scored tickers — skipping alert checks")
        return {}

    logger.info("Running alert checks for %d tickers", len(tickers))

    # Bulk fetch all data in 3 queries
    neg_ratios_by_ticker = _fetch_all_daily_neg_ratios(tickers)
    post_counts_by_ticker = _fetch_all_post_counts(tickers)
    open_alert_pairs = _fetch_open_alerts(tickers)

    to_fire: list[tuple[str, str, float, float]] = []
    fired: dict[str, list[str]] = {}

    for ticker in tickers:
        fired_rules: list[str] = []

        # --- Z-score rule ---
        neg_ratios = neg_ratios_by_ticker.get(ticker, [])
        if len(neg_ratios) >= 3:
            arr = np.array(neg_ratios, dtype=float)
            mean, std = arr.mean(), arr.std()
            if std > 1e-9:
                z = (neg_ratios[-1] - mean) / std
                logger.debug("Ticker %s: z=%.3f", ticker, z)
                if z >= ZSCORE_THRESHOLD and (ticker, "zscore") not in open_alert_pairs:
                    to_fire.append((ticker, "zscore", float(z), ZSCORE_THRESHOLD))
                    fired_rules.append("zscore")

        # --- Volume surge rule ---
        today_count, seven_day_avg = post_counts_by_ticker.get(ticker, (0, 0.0))
        if seven_day_avg >= 1.0:
            surge = today_count / seven_day_avg
            logger.debug("Ticker %s: surge=%.2f", ticker, surge)
            if surge >= VOLUME_SURGE_MULT and (ticker, "volume_surge") not in open_alert_pairs:
                to_fire.append((ticker, "volume_surge", float(surge), VOLUME_SURGE_MULT))
                fired_rules.append("volume_surge")

        if fired_rules:
            fired[ticker] = fired_rules

    _fire_alerts(to_fire)
    logger.info("Alert run complete — %d tickers with new alerts", len(fired))
    return fired


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run_all_checks()
