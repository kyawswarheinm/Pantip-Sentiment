"""Tests for nlp/inference.py — sentiment scoring logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nlp.inference import SentimentPipeline, SentimentResult


class TestSentimentMapping:
    def test_positive_label_gives_positive_sentiment(self):
        result = SentimentResult(label="positive", confidence=0.9, sentiment=0.9)
        assert result.sentiment > 0

    def test_negative_label_gives_negative_sentiment(self):
        result = SentimentResult(label="negative", confidence=0.85, sentiment=-0.85)
        assert result.sentiment < 0

    def test_neutral_label_gives_zero_sentiment(self):
        result = SentimentResult(label="neutral", confidence=0.75, sentiment=0.0)
        assert result.sentiment == 0.0

    def test_compute_sentiment_positive(self):
        score = SentimentPipeline._compute_sentiment("positive", 0.9)
        assert score == pytest.approx(0.9)

    def test_compute_sentiment_negative(self):
        score = SentimentPipeline._compute_sentiment("negative", 0.8)
        assert score == pytest.approx(-0.8)

    def test_compute_sentiment_neutral(self):
        score = SentimentPipeline._compute_sentiment("neutral", 0.95)
        assert score == 0.0


class TestLabelNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("pos", "positive"),
        ("positive", "positive"),
        ("neg", "negative"),
        ("negative", "negative"),
        ("neu", "neutral"),
        ("neutral", "neutral"),
        ("q", "neutral"),
        ("unknown_label", "neutral"),  # falls back to neutral
    ])
    def test_map_label(self, raw, expected):
        result = SentimentPipeline._map_label(raw)
        assert result == expected


class TestBatchInference:
    def _make_pipeline(self, raw_outputs):
        """Create a SentimentPipeline with a mocked HF pipeline."""
        sp = SentimentPipeline.__new__(SentimentPipeline)
        sp._pipeline = MagicMock(return_value=raw_outputs)
        sp._tokenizer = MagicMock()
        sp._model = MagicMock()
        return sp

    def test_returns_none_below_confidence_threshold(self):
        raw = [[{"label": "neg", "score": 0.5}]]  # below 0.65 default
        sp = self._make_pipeline(raw)
        with patch("nlp.inference.CONFIDENCE_THRESHOLD", 0.65):
            results = sp.predict_batch(["ราคาหุ้นตก"])
        assert results[0] is None

    def test_returns_result_above_threshold(self):
        raw = [[{"label": "neg", "score": 0.88}]]
        sp = self._make_pipeline(raw)
        results = sp.predict_batch(["ราคาหุ้นตก"])
        assert results[0] is not None
        assert results[0].label == "negative"
        assert results[0].sentiment < 0

    def test_empty_input_returns_empty(self):
        sp = self._make_pipeline([])
        results = sp.predict_batch([])
        assert results == []

    def test_batch_length_matches_input(self):
        raw = [
            [{"label": "pos", "score": 0.9}],
            [{"label": "neg", "score": 0.8}],
            [{"label": "neu", "score": 0.7}],
        ]
        sp = self._make_pipeline(raw)
        results = sp.predict_batch(["a", "b", "c"])
        assert len(results) == 3
