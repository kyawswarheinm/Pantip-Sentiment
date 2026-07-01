"""
One-time backfill: scrape Pantip boards with aggressive scrolling to collect
~1 month of historical posts, then run NLP scoring on all unscored posts.

Run from the project root:
    python -m scripts.backfill

Environment variables (same as normal pipeline):
    TURSO_URL, TURSO_AUTH_TOKEN, MODEL_NAME, SENTIMENT_CONFIDENCE_THRESHOLD
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("backfill")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCROLL_DEPTH = int(os.getenv("BACKFILL_SCROLLS", "30"))   # scrolls per board page
MAX_POSTS = int(os.getenv("BACKFILL_MAX_POSTS", "2000"))   # total posts ceiling

TARGET_BOARDS = [
    "/tag/หุ้น",
    "/tag/ลงทุน",
    "/tag/กองทุน",
    "/tag/ตลาดหลักทรัพย์",
    "/tag/SET",
]


# ---------------------------------------------------------------------------
# Step 1: Scrape
# ---------------------------------------------------------------------------
def run_scrape() -> int:
    """Scrape boards with deep scrolling; return number of new posts inserted."""
    from scraper.pantip import PantipScraper, _get_existing_ids, _insert_posts

    scraper = PantipScraper()
    existing_ids = _get_existing_ids()
    logger.info("DB already has %d posts — will skip those", len(existing_ids))

    all_posts: list[dict] = []
    try:
        for board in TARGET_BOARDS:
            if len(all_posts) >= MAX_POSTS:
                break

            logger.info("Backfilling board: %s  (scroll_depth=%d)", board, SCROLL_DEPTH)
            url = __import__("urllib.parse", fromlist=["urljoin"]).urljoin(
                os.getenv("PANTIP_BASE_URL", "https://pantip.com"), board
            )

            # Load board page with deep scrolling
            soup = scraper._get_page(url, num_scrolls=SCROLL_DEPTH)
            if soup is None:
                logger.warning("Failed to load %s — skipping", board)
                continue

            from scraper.pantip import _parse_topic_links, _parse_post_page, _extract_post_id
            import time, random

            topic_links = _parse_topic_links(soup)
            logger.info("Found %d topic links on %s", len(topic_links), board)

            board_posts: list[dict] = []
            for link in topic_links:
                if len(all_posts) + len(board_posts) >= MAX_POSTS:
                    break

                post_id = _extract_post_id(link)
                if not post_id or post_id in existing_ids:
                    continue

                topic_soup = scraper._get_page(link)
                if topic_soup is None:
                    continue

                post = _parse_post_page(topic_soup, link, post_id)
                if post:
                    board_posts.append(post)
                    existing_ids.add(post_id)
                    logger.debug("  post %s: %s", post_id, (post.get("title_th") or "")[:60])

            inserted = _insert_posts(board_posts)
            logger.info("Board %s → inserted %d posts", board, inserted)
            all_posts.extend(board_posts)

    finally:
        scraper.close()

    logger.info("Scrape done — %d new posts total", len(all_posts))
    return len(all_posts)


# ---------------------------------------------------------------------------
# Step 2: NLP scoring (reuse existing inference module as-is)
# ---------------------------------------------------------------------------
def run_nlp() -> None:
    """Score all unscored posts — identical to `python -m nlp.inference`."""
    import runpy
    logger.info("Running NLP inference on all unscored posts …")
    runpy.run_module("nlp.inference", run_name="__main__")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("=== Backfill start (scroll_depth=%d, max_posts=%d) ===", SCROLL_DEPTH, MAX_POSTS)
    new_posts = run_scrape()
    if new_posts > 0:
        run_nlp()
    else:
        logger.info("No new posts found — nothing to score.")
    logger.info("=== Backfill complete ===")
