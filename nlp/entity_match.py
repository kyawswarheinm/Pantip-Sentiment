"""
Company-name-to-ticker entity matching.

Matching priority:
  1. Exact ticker symbol in text → 'exact', confidence 1.0
  2. Exact company name (Thai or English) → 'exact', confidence 0.95
  3. Alias dictionary hit → 'alias', confidence 0.90
  4. RapidFuzz token_set_ratio on PyThaiNLP-tokenized text ≥ FUZZY_THRESHOLD
     → 'fuzzy', confidence ratio/100

Fixes applied to reduce fuzzy over-triggering:
  Fix 1 — MIN_FUZZY_ALIAS_LEN = 8: skip any alias < 8 chars in the fuzzy pass.
           Short aliases (e.g. "เดลต้า" = 6 chars) still match via exact
           substring in Pass 2; they are just too dangerous for fuzzy.
  Fix 2 — FUZZY_THRESHOLD = 92: raised from 85. With tokenized text and
           token_set_ratio, 92 is a meaningful signal; 85 was accepting noise.
  Fix 3 — fuzz.token_set_ratio instead of fuzz.partial_ratio: builds token
           sets from both sides and compares intersections, so a single matched
           word contributes proportionally rather than a lucky substring window
           scoring 100%.
  Fix 4 — PyThaiNLP tokenization: segment both the post body and the alias
           with the `newmm` engine before comparison. Thai has no spaces, so
           raw partial_ratio found high-scoring substrings in almost every post.
           After tokenization, word boundaries are explicit and token_set_ratio
           can reason about actual word presence.

Short tickers (≤ 3 chars) still require co-occurrence with at least one
finance keyword to suppress false positives (unchanged).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import NamedTuple

from rapidfuzz import fuzz

from db.client import db_session
from scraper.set_tickers import THAI_ALIASES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PyThaiNLP — optional; gracefully degrade to partial_ratio if missing
# ---------------------------------------------------------------------------
try:
    from pythainlp.tokenize import word_tokenize as _thai_word_tokenize
    _HAS_PYTHAINLP = True
except ImportError:  # pragma: no cover
    _HAS_PYTHAINLP = False
    logger.warning(
        "pythainlp not installed — fuzzy matching falls back to partial_ratio "
        "on raw text (less accurate). Install with: pip install pythainlp"
    )


def _tokenize_thai(text: str) -> str:
    """Segment Thai text into whitespace-separated tokens via PyThaiNLP newmm.
    Returns the raw string unchanged if pythainlp is unavailable.
    """
    if not _HAS_PYTHAINLP:
        return text
    tokens = _thai_word_tokenize(text, engine="newmm", keep_whitespace=False)
    return " ".join(t for t in tokens if t.strip())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FINANCE_KEYWORDS = [
    "หุ้น", "ลงทุน", "ราคา", "ปันผล", "พอร์ต", "เข้า", "ออก",
    "ซื้อ", "ขาย", "ตลาด", "กำไร", "ขาดทุน", "SET", "mai",
    "ผลตอบแทน", "นักลงทุน", "โบรกเกอร์", "เทรด", "fund",
]

# Fix 1: was 4 — too short, produced near-certain partial matches on any post
MIN_FUZZY_ALIAS_LEN = 8

# Fix 2: was 85 — far too permissive with partial_ratio on space-free Thai
FUZZY_THRESHOLD = 92

SHORT_TICKER_MAX_LEN = 3


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class MatchResult(NamedTuple):
    ticker: str
    confidence: float
    method: str   # 'exact', 'alias', 'fuzzy'


@dataclass
class TickerEntry:
    ticker: str
    names: list[str]   # all Thai/English names + aliases, normalised


def _normalise(text: str) -> str:
    return text.strip().lower()


def _has_finance_keyword(text: str) -> bool:
    low = text.lower()
    return any(kw.lower() in low for kw in FINANCE_KEYWORDS)


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------
class EntityMatcher:
    """
    Stateful entity matcher. Call build_index() once after DB has tickers,
    then match() on each post body.
    """

    def __init__(self) -> None:
        self._entries: list[TickerEntry] = []
        self._ticker_set: set[str] = set()

    def build_index(self) -> None:
        """Load tickers from DB and combine with alias dict."""
        with db_session() as db:
            rows = db.fetchall(
                "SELECT ticker, company_name_th, company_name_en FROM tickers"
            )

        self._entries = []
        for row in rows:
            ticker = row["ticker"].strip().upper()
            names: list[str] = []
            if row.get("company_name_th"):
                names.append(row["company_name_th"])
            if row.get("company_name_en"):
                names.append(row["company_name_en"])
            for alias in THAI_ALIASES.get(ticker, []):
                names.append(alias)
            self._entries.append(TickerEntry(ticker=ticker, names=names))

        self._ticker_set = {e.ticker for e in self._entries}
        logger.info(
            "Entity matcher index built: %d tickers  pythainlp=%s  "
            "fuzzy_threshold=%s  min_alias_len=%s",
            len(self._entries), _HAS_PYTHAINLP, FUZZY_THRESHOLD, MIN_FUZZY_ALIAS_LEN,
        )

    def match(self, text: str) -> list[MatchResult]:
        """
        Return all tickers found in `text`, ordered by confidence descending.
        Deduplicates — each ticker appears at most once (highest confidence kept).
        """
        if not self._entries:
            raise RuntimeError("Call build_index() before match()")

        found: dict[str, MatchResult] = {}
        has_finance = _has_finance_keyword(text)

        # ── Pass 1: exact ticker symbol ──────────────────────────────────────
        # Word-boundary regex so "PTT" doesn't match inside "PTTGC".
        words_in_text = set(re.findall(r"\b[A-Z0-9]{1,10}\b", text.upper()))
        for ticker in self._ticker_set:
            if ticker in words_in_text:
                if len(ticker) <= SHORT_TICKER_MAX_LEN and not has_finance:
                    continue
                found[ticker] = MatchResult(ticker=ticker, confidence=1.0, method="exact")

        # ── Pass 2: exact name / alias substring ─────────────────────────────
        text_lower = text.lower()
        for entry in self._entries:
            if entry.ticker in found:
                continue
            for name in entry.names:
                if not name:
                    continue
                if _normalise(name) in text_lower:
                    is_alias = name in THAI_ALIASES.get(entry.ticker, [])
                    confidence = 0.90 if is_alias else 0.95
                    method = "alias" if is_alias else "exact"
                    if len(entry.ticker) <= SHORT_TICKER_MAX_LEN and not has_finance:
                        continue
                    result = MatchResult(ticker=entry.ticker, confidence=confidence, method=method)
                    if entry.ticker not in found or found[entry.ticker].confidence < confidence:
                        found[entry.ticker] = result
                    break

        # ── Pass 3: fuzzy match ───────────────────────────────────────────────
        # Fix 4: tokenize the post body once with PyThaiNLP so word boundaries
        # are explicit. Without this, space-free Thai text lets partial_ratio
        # score any 6-char window at ~100%, matching every post for short aliases.
        text_tokenized = _tokenize_thai(text_lower)

        for entry in self._entries:
            if entry.ticker in found:
                continue

            best_score = 0.0
            for name in entry.names:
                # Fix 1: skip aliases that are too short to be distinctive
                if not name or len(name) < MIN_FUZZY_ALIAS_LEN:
                    continue

                # Fix 4: tokenize the alias too so compound words
                # (e.g. "ธนาคารกสิกรไทย") align with tokenized text tokens
                name_tokenized = _tokenize_thai(_normalise(name))

                # Fix 3: token_set_ratio matches by word-set intersection;
                # a single matched token doesn't saturate the score the way
                # a lucky partial substring would
                if _HAS_PYTHAINLP:
                    score = fuzz.token_set_ratio(name_tokenized, text_tokenized)
                else:
                    # Degraded path — no tokenization, keep partial_ratio but
                    # the stricter threshold (Fix 2) still helps
                    score = fuzz.partial_ratio(_normalise(name), text_lower)

                if score > best_score:
                    best_score = score

            # Fix 2: raised threshold — 92 filters near-random substring hits
            if best_score >= FUZZY_THRESHOLD:
                if len(entry.ticker) <= SHORT_TICKER_MAX_LEN and not has_finance:
                    continue
                found[entry.ticker] = MatchResult(
                    ticker=entry.ticker,
                    confidence=round(best_score / 100, 4),
                    method="fuzzy",
                )

        return sorted(found.values(), key=lambda r: r.confidence, reverse=True)


# ---------------------------------------------------------------------------
# Module-level singleton — build once per process
# ---------------------------------------------------------------------------
_matcher: EntityMatcher | None = None


def get_matcher() -> EntityMatcher:
    """Return the module-level EntityMatcher, building index on first call."""
    global _matcher
    if _matcher is None:
        _matcher = EntityMatcher()
        _matcher.build_index()
    return _matcher


def match_tickers(text: str) -> list[MatchResult]:
    """Convenience wrapper — match tickers in `text` using the singleton."""
    return get_matcher().match(text)
