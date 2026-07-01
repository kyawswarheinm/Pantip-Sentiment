"""Quick diagnostic: show raw model output scores for a sample of posts."""
import os
from dotenv import load_dotenv
load_dotenv()

from db.client import db_session
from nlp.inference import get_pipeline

with db_session() as db:
    rows = db.fetchall("""
        SELECT p.title_th, p.body_th
        FROM posts p
        JOIN post_tickers pt ON pt.post_id = p.post_id
        LEFT JOIN scores s ON s.post_ticker_id = pt.id
        WHERE s.score_id IS NULL
        LIMIT 5
    """)

pipe = get_pipeline()
pipe._ensure_loaded()

for row in rows:
    text = f"{row.get('title_th') or ''} {row.get('body_th') or ''}".strip()[:200]
    raw = pipe._pipeline([text])
    print(f"\nText: {text[:80]}")
    print(f"Raw scores: {raw[0]}")
