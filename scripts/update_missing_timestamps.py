"""
Re-fetch posts to backfill missing data and fix zero reply counts.

Uses plain requests (not Selenium) — much faster, no browser overhead, and
picks up __NEXT_DATA__ JSON embedded in Pantip's SSR HTML which Selenium
often misses due to JS timing.

Usage:
    python scripts/update_missing_timestamps.py [--limit N] [--dry-run]
    python scripts/update_missing_timestamps.py --fix-replies [--limit N] [--dry-run]

Options:
    --limit N      Stop after N posts (default: process all)
    --dry-run      Print what would change without writing to DB
    --fix-replies  Fix replies=0 for posts that already have posted_at
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.client import get_client
from scraper.pantip import _fetch_comment_count, _parse_posted_at

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("update_timestamps.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

DELAY_SECONDS = 1.5
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.119 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://pantip.com/",
}


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.error("  Request failed: %s", exc)
        return None


def _warmup(session: requests.Session) -> None:
    """Visit the homepage to establish pantip_visitc cookie.

    Without it, subsequent topic-page fetches don't receive a PHPSESSID,
    and the render_comments AJAX endpoint returns the homepage instead of JSON.
    """
    try:
        session.get("https://pantip.com/", headers=HEADERS, timeout=15)
        logger.debug("Homepage warmup done; cookies: %s", list(session.cookies.keys()))
    except Exception as exc:
        logger.warning("Homepage warmup failed (AJAX counts may be 0): %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="Max posts to process (0 = all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without writing to DB")
    parser.add_argument("--fix-replies", action="store_true",
                        help="Fix replies=0 for posts that already have posted_at")
    args = parser.parse_args()

    db = get_client()
    try:
        if args.fix_replies:
            rows = db.fetchall(
                "SELECT post_id, url, replies FROM posts "
                "WHERE replies = 0 AND posted_at IS NOT NULL "
                "ORDER BY scraped_at DESC"
            )
            mode = "replies=0 (posted_at already set)"
        else:
            rows = db.fetchall(
                "SELECT post_id, url, replies FROM posts WHERE posted_at IS NULL "
                "ORDER BY scraped_at DESC"
            )
            mode = "posted_at IS NULL"

        total = len(rows)
        if args.limit:
            rows = rows[: args.limit]

        logger.info(
            "Found %d posts with %s — processing %d%s",
            total,
            mode,
            len(rows),
            " (dry-run)" if args.dry_run else "",
        )

        session = requests.Session()
        _warmup(session)
        updated = skipped = failed = 0

        for i, row in enumerate(rows, 1):
            post_id: str = row["post_id"]
            url: str = row["url"]
            current_replies: int = row["replies"] or 0

            pct = i / len(rows) * 100
            logger.info("[%d/%d | %.1f%%] %s", i, len(rows), pct, url)

            # Visiting the topic page sets PHPSESSID + rlr cookies so the
            # render_comments AJAX call below returns JSON instead of HTML.
            soup = fetch_soup(session, url)
            if soup is None:
                failed += 1
                time.sleep(DELAY_SECONDS)
                continue

            api_replies = _fetch_comment_count(session, post_id)
            reply_update = max(current_replies, api_replies)

            if args.fix_replies:
                logger.info("  replies: %d -> %d", current_replies, reply_update)
                if reply_update > current_replies:
                    if not args.dry_run:
                        try:
                            db.execute(
                                "UPDATE posts SET replies = ? WHERE post_id = ?",
                                (reply_update, post_id),
                            )
                            updated += 1
                        except Exception as exc:
                            logger.error("  DB write failed: %s", exc)
                            failed += 1
                    else:
                        updated += 1
                else:
                    skipped += 1  # already correct (genuinely 0 replies)
            else:
                posted_at = _parse_posted_at(soup)
                logger.info(
                    "  posted_at=%s  replies: %d -> %d",
                    posted_at,
                    current_replies,
                    reply_update,
                )
                if posted_at is None:
                    logger.warning("  posted_at still not found — skipping")
                    skipped += 1
                elif not args.dry_run:
                    try:
                        db.execute(
                            "UPDATE posts SET posted_at = ?, replies = ? WHERE post_id = ?",
                            (posted_at.isoformat(), reply_update, post_id),
                        )
                        updated += 1
                    except Exception as exc:
                        logger.error("  DB write failed: %s", exc)
                        failed += 1
                else:
                    updated += 1

            time.sleep(DELAY_SECONDS)

        session.close()
    finally:
        db.close()

    logger.info(
        "Finished — updated: %d | skipped: %d | errors: %d",
        updated, skipped, failed,
    )


if __name__ == "__main__":
    main()
