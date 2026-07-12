# Pantip SET Sentiment Monitor

Thai retail investor discussion on [Pantip.com](https://pantip.com) — Thailand's largest public web forum — mined and scored for sentiment against SET-listed stocks. The pipeline scrapes threads, links them to tickers, runs a multilingual transformer (XLM-RoBERTa), and surfaces the results in a live Streamlit dashboard updated every 12 hours. Built entirely on free-tier infrastructure.

**[Kaggle Dataset](https://www.kaggle.com/datasets/kyawswarheinm/pantip-set-sentiment)** · LICENSE : CC BY-SA 4.0

Visit [Pantip Sentiment Streamlit App](https://pantip-sentiment.streamlit.app/). The dashboard's **📚 Documentation & Analysis** tab covers how the pipeline works, live-computed analysis charts, key findings, and known limitations — that's the primary reference for methodology and results.

---

## Table of contents

- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Running tests](#running-tests)
- [Problems encountered](#problems-encountered)
- [Limitations](#limitations)
- [License](#license)

---

## Quick start

The production database is not publicly shared. There are two ways to work with this project:

### Option A — Explore the data (no credentials needed)

The full scored-posts dataset is published on Kaggle as a CSV. Download it and explore directly:

```bash
git clone https://github.com/kyawswarheinm/pantip-sentiment.git
cd pantip-sentiment
pip install -r requirements.txt

# Download from https://www.kaggle.com/datasets/kyawswarheinm/pantip-set-sentiment
# CSV columns: post_id, title_th, url, replies, posted_at,
#              ticker, match_confidence, match_method,
#              sentiment, confidence, label, scored_at
```

From there you can load it into pandas, a Jupyter notebook, or any SQLite-compatible tool for your own analysis.

### Option B — Run the full pipeline (own infrastructure)

To run the scraper, NLP pipeline, and dashboard against your own database:

```bash
git clone https://github.com/kyawswarheinm/pantip-sentiment.git
cd pantip-sentiment
pip install -r requirements.txt

cp .env.example .env
# Set TURSO_URL + TURSO_AUTH_TOKEN for a cloud DB (free at turso.tech),
# or leave both unset to fall back to a local SQLite file at data/local_dev.db

python -m scraper.set_tickers    # seed ticker list
python -m scraper.pantip          # scrape Pantip (requires Chrome)
python -m nlp.inference           # entity match + sentiment score
python -m alerts.spike_detector   # check alerts
python -m backtest.correlation    # fetch prices + run lag-correlation
streamlit run dashboard/app.py    # launch dashboard
```

---

## Architecture

| Layer | Platform | Free limit | Role |
|---|---|---|---|
| Cron / backend | GitHub Actions | 2,000 min/month | Scrape → entity-link → NLP → alerts → backtest → Kaggle export |
| Database | Turso (LibSQL) | 500 MB, 1B reads/month | Cloud SQLite, accessed via HTTP |
| Frontend | Streamlit Community Cloud | Unlimited public apps | Live dashboard |
| Price data | yfinance | Free | SET ticker OHLCV for lag-correlation backtest |
| Data publishing | Kaggle Datasets | 20 GB | Scored-posts CSV, refreshed every 12 hours |

The active workflow (`scrape.yml`) runs the full chain end-to-end every 12 hours. A second workflow (`kaggle_export.yml`) exists as a standalone export trigger, useful for testing the Kaggle step in isolation.

---

## Project structure

```
scraper/
  pantip.py                    Selenium scraper: headless Chrome, 5 investment tag pages,
                               circuit breaker, 30s page-load timeout
  set_tickers.py               Seeds the 50 SET tickers + Thai alias dictionary into the DB

nlp/
  entity_match.py              Four-pass ticker linker: exact symbol → company name →
                               alias dict → RapidFuzz/PyThaiNLP fuzzy (threshold 92)
  inference.py                 XLM-RoBERTa batch inference; discards predictions below
                               SENTIMENT_CONFIDENCE_THRESHOLD
  check_scores.py              Utility script to inspect score distributions in the DB

alerts/
  spike_detector.py            Z-score (≥ 2.5) and volume-surge (3× 7-day avg) alert engine

backtest/
  correlation.py               Pearson/Spearman lag-correlation (lags 0–5 days) between
                               daily sentiment and yfinance price returns

db/
  client.py                    Turso HTTP pipeline client; auto-falls back to
                               data/local_dev.db if TURSO_URL is unset
  schema.sql                   Table definitions: posts, post_tickers, scores,
                               alerts, prices, kaggle_exports

dashboard/
  app.py                       Entry point: CSS variables, sidebar controls, tab routing
  charts.py                    All Plotly figure builders (data flow, pipeline, funnel,
                               lag correlation, engagement scatter, etc.)
  utils.py                     Cached DB query helpers (@st.cache_data)
  components/
    documentation.py           Documentation & Analysis tab — pipeline docs + live charts
    sentiment_ranking.py       Ranked sentiment table and daily volume bar chart
    sentiment_chart.py         Multi-ticker sentiment trend chart with price overlay
    posts_feed.py              Scrollable recent posts feed
    alert_banner.py            Alert history panel

kaggle/
  export.py                    Queries scored posts → dated CSV at data/exports/ →
                               pushes new dataset version to Kaggle

data/
  set_tickers.csv              Master ticker list with Thai company names and aliases
  exports/                     Local CSV snapshots (git-ignored; pushed to Kaggle)

scripts/
  backfill.py                  One-time deep scrape to populate historical posts
  relink_tickers.py            Re-runs entity matching on all existing posts
                               (use after changing matcher params to reclassify old links)
  update_missing_timestamps.py Patches NULL posted_at via Pantip AJAX endpoint
  generate_readme_charts.py    Generates static PNGs into docs/charts/

tests/
  test_entity_match.py         Entity matching unit tests
  test_inference.py            NLP inference unit tests
  test_spike_detector.py       Alert engine unit tests

.github/workflows/
  scrape.yml                   Full pipeline every 12 hours: scrape → link → NLP →
                               alerts → backtest → Kaggle export
  kaggle_export.yml            Standalone export step (currently disabled;
                               useful for testing the Kaggle step in isolation)
```

---

## Configuration

All variables live in `.env` (see `.env.example`). Only the variables relevant to your use case are needed.

**Database** — if both are unset, the client automatically falls back to a local SQLite file at `data/local_dev.db`.

| Variable | Default | Required for |
|---|---|---|
| `TURSO_URL` | — | Cloud DB (optional — omit for local SQLite) |
| `TURSO_AUTH_TOKEN` | — | Cloud DB (optional — omit for local SQLite) |

**Scraper** — only needed when running `scraper/pantip.py`.

| Variable | Default | Notes |
|---|---|---|
| `PANTIP_BASE_URL` | `https://pantip.com` | Base URL for scraper |
| `SCRAPE_DELAY_MIN` / `MAX` | `2` / `5` | Randomised delay between requests (seconds) |
| `MAX_POSTS_PER_RUN` | `100` | Cap on new posts per scrape run |

**NLP & alerts** — only needed when running `nlp/inference.py` or `alerts/spike_detector.py`.

| Variable | Default | Notes |
|---|---|---|
| `MODEL_NAME` | `cardiffnlp/twitter-xlm-roberta-base-sentiment` | HuggingFace model ID |
| `SENTIMENT_CONFIDENCE_THRESHOLD` | `0.65` | Predictions below this are discarded |
| `ZSCORE_THRESHOLD` | `2.5` | Alert sensitivity (standard deviations) |
| `VOLUME_SURGE_MULTIPLIER` | `3.0` | Alert fires when post count exceeds N × 7-day avg |
| `LOOKBACK_DAYS_ALERT` | `7` | Rolling window for alert baseline |

**Kaggle export** — only needed when running `kaggle/export.py`.

| Variable | Default | Notes |
|---|---|---|
| `KAGGLE_USERNAME` | — | Kaggle account username |
| `KAGGLE_KEY` | — | Kaggle API key |
| `KAGGLE_DATASET_SLUG` | — | e.g. `yourusername/your-dataset-name` |

**Dashboard**

| Variable | Default | Notes |
|---|---|---|
| `STREAMLIT_CACHE_TTL` | `900` | DB query cache lifetime (seconds) |

---

## Running tests

```bash
pytest tests/ -v
```

Covers entity matching (`test_entity_match.py`), inference (`test_inference.py`), and the alert engine (`test_spike_detector.py`).

---

## Problems encountered & How they were solved

Some brain-itching issues were found while building this — kept a log here in case it saves someone else the debugging time.

### While Scraping Reply Counts

- **Pantip's reply counts are loaded by JavaScript — they don't exist in the raw HTML.** The page uses a JsRender template (`{{:count}} ความคิดเห็น`) that only gets filled in after an AJAX call. `requests` + BeautifulSoup only see the empty placeholder. The original HTML parser (`_parse_stats`, later renamed `_parse_replies`) returned 0 for almost every post because of this.

- **Tracked down the real reply counts endpoint — and it kept getting harder to call.** The actual count lives at `GET /forum/topic/render_comments?tid={id}`, found by reading Pantip's own `jquery.topic-renovate.js` in the browser devtools. It only responds if you include `X-Requested-With: XMLHttpRequest` and a `Referer` header — otherwise it returns empty HTML with no error. 

- Pantip later added another requirement: you need a live PHP session (`PHPSESSID` + `rlr` cookies), which only gets set if you visit the homepage and then the topic page in the same `requests.Session()`. The backfill scripts now do this warm-up step before calling the reply counts endpoint.

### While Scraping View Counts 

- **The `views` field was always broken and got removed.** Same root cause as above — view counts(originally meant for engagement analysis) are JS-rendered. Unlike the reply counts, there was no easy API equivalent. `views` was eventually dropped entirely from the schema, scraper, all queries, and the dashboard. This included running `ALTER TABLE … DROP COLUMN` directly on the production database.

### While Parsing Post Timestamps

- **Some posts have a `NULL posted_at`, so the dashboard filters on `scored_at` instead.** Pantip spreads timestamps across JSON-LD, Open Graph tags, `<time>` elements, and `data-utime` attributes — none are guaranteed to be present. When all strategies fail, `posted_at` stays NULL. We use `scored_at` to keep those posts visible in date-range filters, at the cost of answering "what was scored in this window" rather than "what was posted then."

### Bootstrapping the Dataset with Backfill

- **The live scraper only captures what's trending right now — not significant for a correlation study that requires more data.** Pantip's tag pages only surface recent activity, so the pipeline would take months to accumulate enough posts on its own. A one-time backfill (`scripts/backfill.py`) scrolled the same five boards 30× deeper than a normal run, pulling ~2,500 posts back to September 2025 in a single pass. The caveat: only 3 posts predate 2025 — old evergreen threads that resurfaced in a listing — so it's a denser recent slice, not a true historical archive.

### ChromeDriver Version Mismatch Silently Killing 3 Boards

- **Three of five Pantip tag pages returned 0 topic links after Chrome auto-updated on GitHub Actions runners.** The runner installs the latest `google-chrome-stable` on each run, but the `chromedriver` already in PATH was one major version behind (149 vs 150). The version gap caused those heavier JS pages to render blank — `_parse_topic_links` found no `<a href="/topic/...">` links and silently returned empty. The `หุ้น` and `ตลาดหลักทรัพย์` boards still worked because they load faster; `ลงทุน`, `กองทุน`, and `SET` did not.
- **Fixed by switching to `webdriver-manager`.** Adding `ChromeDriverManager().install()` as the `Service` path in `_build_driver()` auto-downloads and caches the exact ChromeDriver version that matches whatever Chrome is installed, regardless of what the runner already has in PATH.

### Turso Free Plan Write Limit Blocking the Pipeline

- **After several months of 3-hourly runs, Turso's free tier hit its monthly row-write quota and started rejecting all `INSERT` statements with `"SQL write operations are forbidden (writes are blocked)"`.** The error propagated all the way up and caused the GitHub Actions job to exit with code 1, meaning no subsequent steps (NLP inference, Kaggle export) ran either.
- **Fixed on two fronts.** First, `_insert_posts` and `score_pending_posts` now catch the `RuntimeError`, log a warning, and return 0 instead of crashing — so the pipeline completes cleanly even when writes are blocked. Second, the cron schedule was reduced from every 3 hours to every 12 hours to cut monthly write volume by 75% and stay within the free tier budget going forward.

---

## Limitations

- **The data is mostly from 2025 onward — it's not a long historical record.** Only 3 of 2,542 scraped posts are from before 2025. Don't treat this as multi-year historical data without checking that your target date range has enough coverage.
- **Some posts have a NULL `posted_at` because Pantip's SSR datetime parser occasionally fails.** Time-series charts use `posted_at` where available and fall back to `scored_at` otherwise — so a small fraction of posts may cluster around the pipeline run date rather than when they were actually written.
- **The Thai company alias dictionary only covers ~50 names.** Tickers outside that list fall back to exact-symbol or fuzzy matching with no alias safety net.
- **There's no human-labeled data to verify accuracy against.** Sentiment scores come from `cardiffnlp/twitter-xlm-roberta-base-sentiment` — a general-purpose multilingual model not fine-tuned on Thai financial text. There is no ground-truth Thai financial sentiment dataset to validate it with.

---

## License

MIT License — © 2026 Kyaw Swar Hein. See [LICENSE](./LICENSE).