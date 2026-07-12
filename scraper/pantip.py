"""
Pantip.com scraper using Selenium + BeautifulSoup.

Targets Thai investment boards, extracts posts, deduplicates against DB,
and writes clean rows to the `posts` table.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from db.client import db_session

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL: str = os.getenv("PANTIP_BASE_URL", "https://pantip.com")
DELAY_MIN: float = float(os.getenv("SCRAPE_DELAY_MIN", "2"))
DELAY_MAX: float = float(os.getenv("SCRAPE_DELAY_MAX", "5"))
MAX_POSTS: int = int(os.getenv("MAX_POSTS_PER_RUN", "100"))
BODY_MAX_CHARS = 2000

# Boards to scrape — Thai investment-related tags
TARGET_BOARDS = [
    "/tag/หุ้น",
    "/tag/ลงทุน",
    "/tag/กองทุน",
    "/tag/ตลาดหลักทรัพย์",
    "/tag/SET",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.119 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.60 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
]


# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------

def _build_driver(ua: str) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-agent={ua}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)  # raise TimeoutException instead of hanging 120s
    return driver


# ---------------------------------------------------------------------------
# Post extraction helpers
# ---------------------------------------------------------------------------

def _extract_post_id(url: str) -> str | None:
    """Extract the Pantip numeric thread ID from a topic URL."""
    match = re.search(r"/topic/(\d+)", url)
    return match.group(1) if match else None


def _parse_datetime(raw: str | None) -> datetime | None:
    """Try every plausible ISO / Thai date format; return None on failure."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",  # Pantip data-utime format: MM/DD/YYYY HH:MM:SS
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
    return None


def _parse_posted_at(soup: BeautifulSoup) -> datetime | None:
    """Multi-strategy posted-at extraction (most reliable first)."""
    import json

    # 0a. Next.js __NEXT_DATA__ JSON (SSR — present in raw HTML, most reliable)
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            nd_data = json.loads(nd.string)
            # Walk common paths Pantip uses for post timestamps
            props = nd_data.get("props", {}).get("pageProps", {})
            for candidate in (
                props.get("post", {}),
                props.get("topic", {}),
                props.get("data", {}),
                props,
            ):
                if not isinstance(candidate, dict):
                    continue
                for key in ("created_at", "published_at", "post_time",
                            "create_time", "datePublished", "dateCreated"):
                    val = candidate.get(key)
                    if val:
                        dt = _parse_datetime(str(val))
                        if dt:
                            return dt
        except Exception:
            pass

    # 0b. Pantip lead:published_at meta (set by client-side JS — may not be in SSR)
    lp = soup.find("meta", attrs={"name": "lead:published_at"})
    if lp and lp.get("content"):
        dt = _parse_datetime(lp["content"])
        if dt:
            return dt

    # 1. JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            for key in ("datePublished", "dateCreated", "dateModified"):
                val = data.get(key) if isinstance(data, dict) else None
                if val:
                    dt = _parse_datetime(str(val))
                    if dt:
                        return dt
        except Exception:
            pass

    # 2. Open Graph / article meta tags
    for prop in ("article:published_time", "article:modified_time", "og:updated_time"):
        m = soup.find("meta", property=prop)
        if m and m.get("content"):
            dt = _parse_datetime(m["content"])
            if dt:
                return dt

    # 3. <time> or <abbr> with datetime attribute
    for tag in soup.find_all(["time", "abbr"], attrs={"datetime": True}):
        dt = _parse_datetime(tag["datetime"])
        if dt:
            return dt

    # 3b. data-utime on <abbr class="timeago"> — Pantip's JS timestamp (MM/DD/YYYY HH:MM:SS)
    for tag in soup.find_all(attrs={"data-utime": True}):
        dt = _parse_datetime(tag["data-utime"])
        if dt and dt.year >= 2010:
            return dt

    # 4. Any element whose datetime attribute looks ISO-like
    for tag in soup.find_all(attrs={"datetime": True}):
        dt = _parse_datetime(tag["datetime"])
        if dt:
            return dt

    # 5. Regex scan: ISO date strings anywhere in the page text
    iso_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
    for match in iso_pattern.finditer(soup.get_text()):
        dt = _parse_datetime(match.group())
        if dt and dt.year >= 2010:
            return dt

    # 6. Thai short-date pattern dd/mm/yyyy HH:MM anywhere in text
    thai_pattern = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})")
    for match in thai_pattern.finditer(soup.get_text()):
        dt = _parse_datetime(f"{match.group(1)} {match.group(2)}")
        if dt:
            return dt

    return None


def _parse_replies(soup: BeautifulSoup) -> int:
    """Extract reply count — only from leaf-level short-text elements."""
    replies = 0

    def _extract_num(tag) -> int | None:
        # Skip containers: if tag has child elements with text it's a wrapper
        if tag.find(True):          # has any child element
            return None
        text = tag.get_text(strip=True).replace(",", "").replace(".", "")
        if len(text) > 20:          # too long — not a bare number
            return None
        num_str = re.sub(r"\D", "", text)
        if not num_str or len(num_str) > 9:   # >9 digits → not a real count
            return None
        return int(num_str)

    # Strategy A: small-text leaf spans/ems whose CLASS names hint at stats
    for tag in soup.find_all(["span", "em", "small"],
                              class_=re.compile(r"stat|count|reply|comment|ตอบ", re.I)):
        num = _extract_num(tag)
        if num is None:
            continue
        # Check the immediate parent's full HTML for keyword context
        ctx = (str(tag.parent) if tag.parent else str(tag)).lower()
        if "ตอบ" in ctx or "comment" in ctx or "reply" in ctx:
            replies = max(replies, num)

    # Strategy B: explicit count data-* attributes only
    # NOTE: data-comment / data-reply are comment *IDs* on Pantip, not counts — excluded
    for attr in ("data-replycount", "data-commentcount"):
        for tag in soup.find_all(attrs={attr: True}):
            try:
                val = int(re.sub(r"\D", "", str(tag[attr])))
                if val < 1_000_000:   # sanity cap
                    replies = max(replies, val)
            except (ValueError, TypeError):
                pass

    # Strategy C: comment-counter element (Pantip shows "9 Comments" / "9 ความคิดเห็น")
    if not replies:
        counter_el = soup.find(id="comment-counter")
        if counter_el:
            text = counter_el.get_text(strip=True).replace(",", "")
            m = re.search(r"(\d+)", text)
            if m:
                val = int(m.group(1))
                if 0 < val < 1_000_000:
                    replies = val

    return replies


def _fetch_comment_count(session, topic_id: str) -> int:
    """Return the true comment count from Pantip's render_comments AJAX endpoint.

    Requires the session to already hold a PHPSESSID + pantip_visitc cookie pair,
    which is established by visiting the homepage then the topic page first.
    The response body starts with a BOM (﻿) before valid JSON.
    """
    url = f"{BASE_URL}/forum/topic/render_comments?tid={topic_id}&param=&type=&time=0"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/topic/{topic_id}",
    }
    try:
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        count = data.get("count", 0)
        if isinstance(count, (int, float)) and 0 <= count < 100_000:
            return int(count)
    except Exception as exc:
        logger.debug("comment-count API failed for topic %s: %s", topic_id, exc)
    return 0


def _parse_post_page(soup: BeautifulSoup, url: str, post_id: str) -> dict[str, Any] | None:
    """Extract structured data from a single Pantip topic page."""
    title_tag = soup.find("h2", class_=re.compile(r"display-post-title"))
    if not title_tag:
        title_tag = soup.find("h1")
    title_th = title_tag.get_text(strip=True) if title_tag else None

    body_tag = soup.find("div", class_=re.compile(r"display-post-story"))
    body_th = None
    if body_tag:
        body_th = body_tag.get_text(" ", strip=True)[:BODY_MAX_CHARS]

    replies = _parse_replies(soup)
    posted_at = _parse_posted_at(soup)

    return {
        "post_id": post_id,
        "url": url,
        "title_th": title_th,
        "body_th": body_th,
        "replies": replies,
        "posted_at": posted_at.isoformat() if posted_at else None,
    }


def _parse_topic_links(soup: BeautifulSoup) -> list[str]:
    """Return all topic URLs found on a board/tag listing page."""
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "/topic/" in href:
            full = href if href.startswith("http") else urljoin(BASE_URL, href)
            links.append(full)
    return list(dict.fromkeys(links))  # preserve order, deduplicate


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_existing_ids() -> set[str]:
    """Fetch all post_ids already in the DB to avoid re-scraping."""
    with db_session() as db:
        rows = db.fetchall("SELECT post_id FROM posts")
    return {r["post_id"] for r in rows}


def _insert_posts(posts: list[dict[str, Any]]) -> int:
    """Bulk-insert new posts; skip duplicates via INSERT OR IGNORE."""
    if not posts:
        return 0
    sql = """
        INSERT OR IGNORE INTO posts (post_id, url, title_th, body_th, replies, posted_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            p["post_id"],
            p["url"],
            p["title_th"],
            p["body_th"],
            p["replies"],
            p["posted_at"],
        )
        for p in posts
    ]
    try:
        with db_session() as db:
            db.executemany(sql, rows)
        return len(rows)
    except RuntimeError as exc:
        if "writes are blocked" in str(exc) or "forbidden" in str(exc).lower():
            logger.warning("Turso write limit reached — %d posts scraped but not stored", len(rows))
            return 0
        raise


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class PantipScraper:
    """Stateful scraper with circuit-breaker and per-run deduplication."""

    def __init__(self) -> None:
        self._ua = random.choice(USER_AGENTS)
        self._driver: webdriver.Chrome | None = None
        self._session = requests.Session()
        self._session.headers["User-Agent"] = self._ua
        self._consecutive_errors = 0
        self._circuit_open = False

    def _sync_cookies(self) -> None:
        """Copy live Selenium cookies into the requests session for AJAX calls."""
        if self._driver is None:
            return
        self._session.cookies.clear()
        for c in self._driver.get_cookies():
            self._session.cookies.set(c["name"], c["value"])

    def _get_driver(self) -> webdriver.Chrome:
        if self._driver is None:
            self._driver = _build_driver(self._ua)
        return self._driver

    def _random_delay(self) -> None:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    def _check_circuit(self) -> None:
        if self._consecutive_errors >= 3:
            logger.warning("Circuit breaker open — sleeping 60s")
            time.sleep(60)
            self._consecutive_errors = 0
            self._circuit_open = False

    def _get_page(self, url: str, num_scrolls: int = 0) -> BeautifulSoup | None:
        self._check_circuit()
        driver = self._get_driver()
        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            for _ in range(num_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
            self._random_delay()
            html = driver.page_source
            self._consecutive_errors = 0
            return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            self._consecutive_errors += 1
            logger.error("Error fetching %s (%d/3): %s", url, self._consecutive_errors, exc)
            # Recreate driver if the ChromeDriver connection itself died
            if self._driver:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None
            return None

    def scrape_board(self, board_path: str, existing_ids: set[str]) -> list[dict[str, Any]]:
        """Scrape one board/tag page and return new post data."""
        url = urljoin(BASE_URL, board_path)
        logger.info("Scraping board: %s", url)
        soup = self._get_page(url, num_scrolls=5)
        if soup is None:
            return []

        topic_links = _parse_topic_links(soup)
        logger.info("Found %d topic links on %s", len(topic_links), board_path)

        posts: list[dict[str, Any]] = []
        for link in topic_links:
            post_id = _extract_post_id(link)
            if not post_id or post_id in existing_ids:
                continue

            topic_soup = self._get_page(link)
            if topic_soup is None:
                continue

            post = _parse_post_page(topic_soup, link, post_id)
            if post:
                self._sync_cookies()
                ajax_count = _fetch_comment_count(self._session, post_id)
                if ajax_count > 0:
                    post["replies"] = ajax_count
                posts.append(post)
                existing_ids.add(post_id)  # prevent re-fetch within same run
                logger.debug("Scraped post %s: %s", post_id, (post.get("title_th") or "")[:60])

            if len(posts) >= MAX_POSTS:
                break

        return posts

    def run(self) -> int:
        """
        Full scrape run across all TARGET_BOARDS.
        Returns total number of new posts inserted.
        """
        existing_ids = _get_existing_ids()
        logger.info("Found %d existing post IDs in DB", len(existing_ids))

        all_posts: list[dict[str, Any]] = []
        for board in TARGET_BOARDS:
            if len(all_posts) >= MAX_POSTS:
                break
            board_posts = self.scrape_board(board, existing_ids)
            all_posts.extend(board_posts)
            logger.info("Board %s yielded %d new posts", board, len(board_posts))

        inserted = _insert_posts(all_posts)
        logger.info("Inserted %d new posts", inserted)
        return inserted

    def close(self) -> None:
        if self._driver:
            self._driver.quit()
            self._driver = None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    scraper = PantipScraper()
    try:
        count = scraper.run()
        logger.info("Scrape complete — %d posts stored", count)
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
