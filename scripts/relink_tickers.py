"""
Re-run entity matching on all posts with the improved matcher and reconcile
the post_tickers + scores tables.

What this does per post:
  - Runs new match_tickers() (Fix 1-4: min alias length, higher threshold,
    token_set_ratio, PyThaiNLP tokenization)
  - Removes post_ticker rows the new matcher rejects (deletes dependent scores
    first — no CASCADE in schema)
  - Inserts post_ticker rows the new matcher finds but didn't exist before
  - Updates confidence/method on rows that are still matched but changed

After reconciliation it runs score_pending_posts() to score any new
post_ticker rows that don't have a score yet.

Run from the project root:
    python -m scripts.relink_tickers              # live run
    python -m scripts.relink_tickers --dry-run    # preview, no DB writes
    python -m scripts.relink_tickers --no-score   # relink only, skip NLP

Expected outcome: fuzzy share drops from ~94% to well under 20%.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("relink")

BATCH_SIZE = 100   # posts per DB commit


@dataclass
class Stats:
    posts_processed: int = 0
    posts_empty_pruned: int = 0  # posts with no text whose links were deleted
    links_removed: int = 0
    scores_removed: int = 0
    links_added: int = 0
    links_updated: int = 0   # confidence/method changed but ticker kept
    links_unchanged: int = 0
    posts_no_match: int = 0   # posts that ended up with zero ticker links
    match_errors: int = 0    # match() raised an unexpected exception
    method_counts: dict[str, int] = field(default_factory=lambda: {"exact": 0, "alias": 0, "fuzzy": 0})


def _load_all_posts(db) -> list[dict]:
    return db.fetchall(
        "SELECT post_id, title_th, body_th FROM posts ORDER BY post_id"
    )


def _load_existing_links(db, post_ids: list[str]) -> dict[str, dict[str, dict]]:
    """Return {post_id: {ticker: {id, confidence, method}}} for the given batch."""
    if not post_ids:
        return {}
    placeholders = ",".join("?" * len(post_ids))
    rows = db.fetchall(
        f"SELECT id, post_id, ticker, match_confidence, match_method "
        f"FROM post_tickers WHERE post_id IN ({placeholders})",
        post_ids,
    )
    result: dict[str, dict[str, dict]] = {}
    for r in rows:
        result.setdefault(r["post_id"], {})[r["ticker"]] = {
            "id": r["id"],
            "confidence": r["match_confidence"],
            "method": r["match_method"],
        }
    return result


_DELETE_CHUNK = 200  # stay well below SQLite's 999-variable limit


def _delete_links(db, pt_ids: list[int]) -> int:
    """Delete scores then post_tickers for the given IDs. Returns score rows deleted."""
    if not pt_ids:
        return 0
    total_scores = 0
    for i in range(0, len(pt_ids), _DELETE_CHUNK):
        chunk = pt_ids[i : i + _DELETE_CHUNK]
        ph = ",".join("?" * len(chunk))
        total_scores += db.fetchall(
            f"SELECT COUNT(*) c FROM scores WHERE post_ticker_id IN ({ph})", chunk
        )[0]["c"]
        db.execute(f"DELETE FROM scores WHERE post_ticker_id IN ({ph})", chunk)
        db.execute(f"DELETE FROM post_tickers WHERE id IN ({ph})", chunk)
    return total_scores


def reconcile_batch(
    db,
    posts: list[dict],
    existing_links: dict[str, dict[str, dict]],
    matcher,
    stats: Stats,
    dry_run: bool,
) -> None:
    """Reconcile one batch of posts. All DB writes happen inside this call."""
    to_remove_ids: list[int] = []
    to_insert: list[tuple] = []          # (post_id, ticker, confidence, method)
    to_update: list[tuple] = []          # (confidence, method, id)

    for post in posts:
        post_id = post["post_id"]
        text = " ".join(filter(None, [post.get("title_th"), post.get("body_th")]))
        if not text.strip():
            # Post has no content — delete all its links (can never produce a score).
            for old in existing_links.get(post_id, {}).values():
                to_remove_ids.append(old["id"])
                stats.links_removed += 1
            stats.posts_empty_pruned += 1
            continue

        try:
            new_matches = {
                r.ticker: {"confidence": r.confidence, "method": r.method}
                for r in matcher.match(text)
            }
        except Exception as exc:
            logger.warning("match() failed for %s: %s", post_id, exc)
            stats.match_errors += 1
            continue

        old_links = existing_links.get(post_id, {})

        # Tickers to remove: existed before but new matcher rejects them
        for ticker, old in old_links.items():
            if ticker not in new_matches:
                to_remove_ids.append(old["id"])
                stats.links_removed += 1

        # Tickers to insert or update
        for ticker, new in new_matches.items():
            stats.method_counts[new["method"]] = (
                stats.method_counts.get(new["method"], 0) + 1
            )
            if ticker not in old_links:
                to_insert.append((post_id, ticker, new["confidence"], new["method"]))
                stats.links_added += 1
            else:
                old = old_links[ticker]
                if (
                    abs((old["confidence"] or 0) - new["confidence"]) > 0.001
                    or old["method"] != new["method"]
                ):
                    to_update.append((new["confidence"], new["method"], old["id"]))
                    stats.links_updated += 1
                else:
                    stats.links_unchanged += 1

        if not new_matches:
            stats.posts_no_match += 1

        stats.posts_processed += 1

    if dry_run:
        logger.info(
            "  [dry-run] would remove %d links (%d score rows), "
            "insert %d, update %d",
            len(to_remove_ids), 0, len(to_insert), len(to_update),
        )
        return

    # Apply all changes in one batch
    scores_deleted = _delete_links(db, to_remove_ids)
    stats.scores_removed += scores_deleted

    if to_insert:
        db.executemany(
            "INSERT OR IGNORE INTO post_tickers "
            "(post_id, ticker, match_confidence, match_method) VALUES (?, ?, ?, ?)",
            to_insert,
        )

    if to_update:
        db.executemany(
            "UPDATE post_tickers SET match_confidence=?, match_method=? WHERE id=?",
            to_update,
        )


def run_relink(dry_run: bool = False, no_score: bool = False) -> Stats:
    from db.client import db_session
    from nlp.entity_match import get_matcher

    logger.info("Building entity matcher index …")
    matcher = get_matcher()

    stats = Stats()

    with db_session() as db:
        posts = _load_all_posts(db)

    logger.info("Relinking %d posts (dry_run=%s) …", len(posts), dry_run)

    for batch_start in range(0, len(posts), BATCH_SIZE):
        batch = posts[batch_start : batch_start + BATCH_SIZE]
        batch_ids = [p["post_id"] for p in batch]

        with db_session() as db:
            existing = _load_existing_links(db, batch_ids)
            reconcile_batch(db, batch, existing, matcher, stats, dry_run)

        pct = (batch_start + len(batch)) / len(posts) * 100
        logger.info(
            "  %d/%d posts (%.0f%%) | removed=%d added=%d updated=%d pruned=%d err=%d",
            batch_start + len(batch), len(posts), pct,
            stats.links_removed, stats.links_added, stats.links_updated,
            stats.posts_empty_pruned, stats.match_errors,
        )

    # Summary
    total_new = sum(stats.method_counts.values())
    logger.info("═" * 60)
    logger.info("Relink complete")
    logger.info("  Posts processed : %d", stats.posts_processed)
    logger.info("  Posts empty (pruned) : %d  (no text — all their links removed)", stats.posts_empty_pruned)
    logger.info("  Links removed   : %d  (+ %d scores deleted)", stats.links_removed, stats.scores_removed)
    logger.info("  Links added     : %d", stats.links_added)
    logger.info("  Links updated   : %d  (confidence/method changed)", stats.links_updated)
    logger.info("  Links unchanged : %d", stats.links_unchanged)
    logger.info("  Posts with zero links: %d", stats.posts_no_match)
    if total_new:
        for method, count in sorted(stats.method_counts.items()):
            logger.info("  %-10s : %d  (%.0f%%)", method, count, count / total_new * 100)
    if stats.match_errors:
        logger.warning("  match() errors  : %d", stats.match_errors)
    logger.info("═" * 60)

    if dry_run:
        logger.info("Dry-run — no changes written.")
        return stats

    if no_score:
        logger.info("--no-score set — skipping NLP inference.")
        return stats

    # Score the new unscored post_tickers
    logger.info("Running NLP inference on new unscored post_ticker rows …")
    from nlp.inference import score_pending_posts
    new_scores = score_pending_posts()
    logger.info("Scored %d new rows.", new_scores)

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-run entity matching on all posts")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing to DB",
    )
    parser.add_argument(
        "--no-score", action="store_true",
        help="Relink only — skip NLP inference after relinking",
    )
    args = parser.parse_args()
    run_relink(dry_run=args.dry_run, no_score=args.no_score)
