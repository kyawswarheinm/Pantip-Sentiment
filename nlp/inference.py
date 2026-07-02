"""
WangchanBERTa sentiment inference pipeline.

Loads `airesearch/wangchanberta-base-att-spm-uncased` from HuggingFace.
If fine-tuned weights exist at models/wangchanberta_finetuned.pt, those
are loaded on top of the base model.

Output: for each text, a (label, confidence, sentiment_score) triple where
  sentiment_score ∈ [-1.0, 1.0]:
    positive → +confidence
    neutral  →  0.0
    negative → -confidence
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from dotenv import load_dotenv
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline,
)

load_dotenv()
logger = logging.getLogger(__name__)

# Default: multilingual XLM-RoBERTa fine-tuned on Twitter sentiment (30+ languages, Thai included).
# Override with a WangchanBERTa fine-tune once Kaggle GPU training is complete.
MODEL_NAME: str = os.getenv(
    "MODEL_NAME", "cardiffnlp/twitter-xlm-roberta-base-sentiment"
)
CONFIDENCE_THRESHOLD: float = float(
    os.getenv("SENTIMENT_CONFIDENCE_THRESHOLD", "0.55")
)
FINE_TUNED_PATH = Path(__file__).parent.parent / "models" / "wangchanberta_finetuned.pt"

# Normalise raw model label strings to positive / neutral / negative.
# Covers WangchanBERTa (pos/neg/neu/q) and XLM-RoBERTa (LABEL_0/1/2 or full words).
_LABEL_MAP: dict[str, str] = {
    # WangchanBERTa / Wisesight variants
    "pos": "positive",
    "neg": "negative",
    "neu": "neutral",
    "q": "neutral",
    # Full-word variants
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
    # Cardiff XLM-RoBERTa numeric fallback (id2label not always applied by pipeline)
    "label_0": "negative",
    "label_1": "neutral",
    "label_2": "positive",
}

MAX_LENGTH = 510  # WangchanBERTa position IDs offset by 2; 512 causes OOB gather
BATCH_SIZE = 16


@dataclass
class SentimentResult:
    label: str        # 'positive', 'neutral', 'negative'
    confidence: float  # softmax max probability
    sentiment: float  # continuous [-1.0, 1.0]


class SentimentPipeline:
    """
    Cached inference pipeline.  Instantiate once per process.
    The HuggingFace pipeline is loaded lazily on first call.
    """

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._tokenizer: Any = None
        self._model: Any = None

    def _load(self) -> None:
        """Load model and tokenizer into memory (called once)."""
        logger.info("Loading tokenizer from %s", MODEL_NAME)
        self._tokenizer = AutoTokenizer.from_pretrained(
            MODEL_NAME, use_fast=False
        )

        logger.info("Loading model from %s", MODEL_NAME)
        self._model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)

        if FINE_TUNED_PATH.exists():
            logger.info("Loading fine-tuned weights from %s", FINE_TUNED_PATH)
            state = torch.load(FINE_TUNED_PATH, map_location="cpu")
            self._model.load_state_dict(state, strict=False)

        device = 0 if torch.cuda.is_available() else -1
        logger.info("Using device: %s", "CUDA" if device == 0 else "CPU")

        self._pipeline = pipeline(
            "text-classification",
            model=self._model,
            tokenizer=self._tokenizer,
            device=device,
            top_k=None,  # return all label scores
            truncation=True,
            max_length=MAX_LENGTH,
        )
        logger.info("Sentiment pipeline ready")

    def _ensure_loaded(self) -> None:
        if self._pipeline is None:
            self._load()

    @staticmethod
    def _map_label(raw_label: str) -> str:
        return _LABEL_MAP.get(raw_label.lower(), "neutral")

    @staticmethod
    def _compute_sentiment(label: str, confidence: float) -> float:
        if label == "positive":
            return round(confidence, 4)
        if label == "negative":
            return round(-confidence, 4)
        return 0.0

    def predict_one(self, text: str) -> SentimentResult | None:
        """
        Score a single text.  Returns None if confidence is below threshold.
        """
        results = self.predict_batch([text])
        return results[0]

    def predict_batch(self, texts: list[str]) -> list[SentimentResult | None]:
        """
        Batch inference.  Returns None for items below confidence threshold.
        """
        self._ensure_loaded()
        if not texts:
            return []

        # The pipeline returns a list-of-lists when top_k=None
        raw_outputs: list[list[dict[str, Any]]] = self._pipeline(
            texts, batch_size=BATCH_SIZE
        )

        results: list[SentimentResult | None] = []
        for text_scores in raw_outputs:
            # text_scores = [{"label": "...", "score": 0.9}, ...]
            best = max(text_scores, key=lambda d: d["score"])
            label = self._map_label(best["label"])
            confidence = round(float(best["score"]), 4)

            if confidence < CONFIDENCE_THRESHOLD:
                results.append(None)
                continue

            sentiment = self._compute_sentiment(label, confidence)
            results.append(SentimentResult(label=label, confidence=confidence, sentiment=sentiment))

        return results


# Module-level singleton
_pipeline_instance: SentimentPipeline | None = None


def get_pipeline() -> SentimentPipeline:
    """Return the module-level SentimentPipeline, loading once per process."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = SentimentPipeline()
    return _pipeline_instance


# ---------------------------------------------------------------------------
# DB integration — score unscored post_ticker rows
# ---------------------------------------------------------------------------

def score_pending_posts() -> int:
    """
    Find all post_ticker rows without a score, run inference, and write
    results to the `scores` table.  Returns number of new score rows added.
    """
    from db.client import db_session

    with db_session() as db:
        pending = db.fetchall(
            """
            SELECT pt.id AS post_ticker_id, p.title_th, p.body_th
            FROM post_tickers pt
            JOIN posts p ON p.post_id = pt.post_id
            LEFT JOIN scores s ON s.post_ticker_id = pt.id
            WHERE s.score_id IS NULL
            """
        )

    if not pending:
        logger.info("No pending post_ticker rows to score")
        return 0

    logger.info("Scoring %d post_ticker rows", len(pending))
    pipe = get_pipeline()

    # Build text corpus: combine title + body for richer context
    texts = [
        f"{r.get('title_th') or ''} {r.get('body_th') or ''}".strip()
        for r in pending
    ]

    predictions = pipe.predict_batch(texts)

    score_rows = []
    for record, pred in zip(pending, predictions):
        if pred is None:
            continue
        score_rows.append(
            (
                record["post_ticker_id"],
                pred.sentiment,
                pred.confidence,
                pred.label,
            )
        )

    if not score_rows:
        logger.info("No predictions exceeded confidence threshold")
        return 0

    sql = """
        INSERT INTO scores (post_ticker_id, sentiment, confidence, label)
        VALUES (?, ?, ?, ?)
    """
    with db_session() as db:
        db.executemany(sql, score_rows)

    logger.info("Inserted %d score rows", len(score_rows))
    return len(score_rows)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    # Also run entity matching on unlinked posts before scoring
    from nlp.entity_match import get_matcher
    from db.client import db_session

    matcher = get_matcher()

    with db_session() as db:
        unlinked = db.fetchall(
            """
            SELECT p.post_id, p.title_th, p.body_th
            FROM posts p
            LEFT JOIN post_tickers pt ON pt.post_id = p.post_id
            WHERE pt.id IS NULL
            """
        )

    logger.info("Linking %d unlinked posts to tickers", len(unlinked))
    link_rows = []
    for post in unlinked:
        text = f"{post.get('title_th') or ''} {post.get('body_th') or ''}"
        matches = matcher.match(text)
        for m in matches:
            link_rows.append((post["post_id"], m.ticker, m.confidence, m.method))

    if link_rows:
        with db_session() as db:
            db.executemany(
                """
                INSERT OR IGNORE INTO post_tickers (post_id, ticker, match_confidence, match_method)
                VALUES (?, ?, ?, ?)
                """,
                link_rows,
            )
        logger.info("Inserted %d post_ticker links", len(link_rows))

    score_pending_posts()


if __name__ == "__main__":
    main()
