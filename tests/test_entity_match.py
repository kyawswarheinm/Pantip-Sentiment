"""Tests for nlp/entity_match.py — entity linking logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nlp.entity_match import EntityMatcher, MatchResult


def _make_matcher(db_rows: list[dict]) -> EntityMatcher:
    """Build an EntityMatcher with mocked DB data."""
    matcher = EntityMatcher()
    with patch("nlp.entity_match.db_session") as mock_ctx:
        mock_db = MagicMock()
        mock_db.fetchall.return_value = db_rows
        mock_ctx.return_value.__enter__ = lambda s: mock_db
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        matcher.build_index()
    return matcher


SAMPLE_TICKERS = [
    {"ticker": "PTT", "company_name_th": "ปตท", "company_name_en": "PTT Public Company Limited"},
    {"ticker": "KBANK", "company_name_th": "กสิกรไทย", "company_name_en": "Kasikorn Bank"},
    {"ticker": "ADVANC", "company_name_th": "แอดวานซ์", "company_name_en": "Advanced Info Service"},
    {"ticker": "BBL", "company_name_th": "กรุงเทพ", "company_name_en": "Bangkok Bank"},
]


class TestExactTickerMatch:
    def test_matches_ticker_in_text(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("ราคาหุ้น KBANK วันนี้ขึ้นมาก")
        tickers = [r.ticker for r in results]
        assert "KBANK" in tickers

    def test_exact_match_confidence_is_one(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("ราคาหุ้น KBANK วันนี้ขึ้นมาก")
        kbank = next(r for r in results if r.ticker == "KBANK")
        assert kbank.confidence == 1.0
        assert kbank.method == "exact"

    def test_does_not_partial_match_ptt_in_pttgc(self):
        """PTT should not match inside PTTGC."""
        rows = SAMPLE_TICKERS + [
            {"ticker": "PTTGC", "company_name_th": "พีทีทีจีซี", "company_name_en": "PTT Global Chemical"}
        ]
        matcher = _make_matcher(rows)
        results = matcher.match("ลงทุนใน PTTGC ดีไหม")
        tickers = {r.ticker for r in results}
        # PTTGC should match, PTT should NOT
        assert "PTTGC" in tickers
        assert "PTT" not in tickers


class TestShortTickerGuard:
    def test_short_ticker_without_finance_keyword_suppressed(self):
        """BBL (3 chars) should not match a non-finance text."""
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("BBL คือชื่อสถานที่")
        tickers = [r.ticker for r in results]
        assert "BBL" not in tickers

    def test_short_ticker_with_finance_keyword_allowed(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("หุ้น BBL ราคาดี")
        tickers = [r.ticker for r in results]
        assert "BBL" in tickers


class TestAliasMatch:
    def test_thai_alias_matches(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("ปตท มีกำไรดีมาก ลงทุนหุ้น")
        tickers = [r.ticker for r in results]
        assert "PTT" in tickers

    def test_alias_method_label(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("ปตท มีกำไรดีมาก ลงทุนหุ้น")
        ptt = next((r for r in results if r.ticker == "PTT"), None)
        assert ptt is not None
        assert ptt.method in ("alias", "exact")


class TestDeduplication:
    def test_no_duplicate_tickers_returned(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        results = matcher.match("หุ้น KBANK กสิกรไทย ราคาขึ้น")
        tickers = [r.ticker for r in results]
        assert len(tickers) == len(set(tickers))

    def test_empty_text_returns_empty(self):
        matcher = _make_matcher(SAMPLE_TICKERS)
        assert matcher.match("") == []
