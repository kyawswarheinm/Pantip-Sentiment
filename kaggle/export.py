"""
Weekly Kaggle dataset exporter.

Queries all scored posts, writes a versioned CSV to data/exports/, then
pushes a new dataset version via the Kaggle API.  Logs the export to the
`kaggle_exports` table.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path


def _kaggle_env() -> dict:
    """Build env vars for the kaggle CLI subprocess.
    New-style KGAT_ tokens use KAGGLE_API_TOKEN; legacy keys use USERNAME+KEY."""
    env = os.environ.copy()
    key = os.getenv("KAGGLE_KEY", "") or os.getenv("KAGGLE_API_TOKEN", "")
    if key.startswith("KGAT_"):
        env["KAGGLE_API_TOKEN"] = key
    return env

import pandas as pd
from dotenv import load_dotenv

from db.client import db_session

load_dotenv()
logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).parent.parent / "data" / "exports"
DATASET_SLUG: str = os.getenv("KAGGLE_DATASET_SLUG", "")
KAGGLE_USERNAME: str = os.getenv("KAGGLE_USERNAME", "")


def _query_scored_posts() -> pd.DataFrame:
    """Return the full scored-posts dataset as a DataFrame."""
    with db_session() as db:
        rows = db.fetchall(
            """
            SELECT
                p.post_id,
                p.title_th,
                p.url,
                p.replies,
                p.posted_at,
                pt.ticker,
                pt.match_confidence,
                pt.match_method,
                s.sentiment,
                s.confidence,
                s.label,
                s.scored_at
            FROM scores s
            JOIN post_tickers pt ON pt.id = s.post_ticker_id
            JOIN posts p ON p.post_id = pt.post_id
            ORDER BY p.posted_at DESC
            """
        )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df


def export_to_csv(df: pd.DataFrame) -> Path:
    """Write the DataFrame to a dated CSV file in data/exports/."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y%m%d")
    path = EXPORT_DIR / f"pantip_set_sentiment_{today}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("Exported %d rows to %s", len(df), path)
    return path


def _dataset_exists() -> bool:
    """Check if the dataset already exists on Kaggle."""
    if not DATASET_SLUG:
        return False
    result = subprocess.run(
        ["kaggle", "datasets", "status", DATASET_SLUG],
        capture_output=True, text=True, timeout=30,
        env=_kaggle_env(),
    )
    return result.returncode == 0


def push_to_kaggle(export_path: Path, row_count: int) -> bool:
    """
    Push data to Kaggle — creates the dataset on first run, versions it on subsequent runs.
    Returns True on success.
    """
    if not KAGGLE_USERNAME:
        logger.error("KAGGLE_USERNAME not set — cannot push to Kaggle")
        return False

    export_dir = str(export_path.parent)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    message = f"Auto-update {date_str} ({row_count:,} rows)"

    # First time: create the dataset
    if not _dataset_exists():
        logger.info("Dataset not found — creating for the first time")
        cmd = ["kaggle", "datasets", "create", "-p", export_dir, "--dir-mode", "zip"]
    else:
        cmd = [
            "kaggle", "datasets", "version",
            "-p", export_dir,
            "-m", message,
            "--dir-mode", "zip",
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=_kaggle_env())
        if result.returncode == 0:
            logger.info("Kaggle push OK: %s", message)
            if DATASET_SLUG:
                _log_export(DATASET_SLUG, message, row_count)
            return True
        else:
            logger.error("Kaggle push failed: %s", result.stderr)
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("Kaggle CLI error: %s", exc)
        return False


def _log_export(dataset_slug: str, version_note: str, rows_exported: int) -> None:
    """Record the export in the kaggle_exports audit table."""
    with db_session() as db:
        db.execute(
            """
            INSERT INTO kaggle_exports (dataset_slug, version_note, rows_exported)
            VALUES (?, ?, ?)
            """,
            (dataset_slug, version_note, rows_exported),
        )


def run_export() -> None:
    """Full export pipeline: query → CSV → Kaggle push."""
    logger.info("Starting Kaggle export")
    df = _query_scored_posts()
    if df.empty:
        logger.warning("No scored posts to export")
        return

    csv_path = export_to_csv(df)
    success = push_to_kaggle(csv_path, len(df))
    if success:
        logger.info("Kaggle export complete — %d rows", len(df))
    else:
        logger.warning("CSV saved locally at %s but Kaggle push failed", csv_path)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run_export()
