"""
SET ticker downloader and DB seeder.

Downloads the listed-company CSV from set.or.th, parses it, and upserts
rows into the `tickers` table.  Also maintains a hardcoded Thai-name alias
dictionary for the top-50 most-traded companies used by entity_match.py.
"""

from __future__ import annotations

import csv
import logging
import os
from io import StringIO
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from db.client import db_session

load_dotenv()
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
TICKERS_CSV = DATA_DIR / "set_tickers.csv"

# SET listed-company CSV endpoint (English interface)
SET_CSV_URL = (
    "https://www.set.or.th/en/market/product/stock/quote/-/asset_publisher/"
    "I2xET4pABMDN/content/listed-companies"
)

# Fallback direct download URL used by set.or.th data export
SET_DOWNLOAD_URL = "https://www.set.or.th/dat/eod/listedCompany/listedCompanies_en.csv"

# ---------------------------------------------------------------------------
# Top-50 Thai alias dictionary  (ticker → list of Thai name variants)
# ---------------------------------------------------------------------------
THAI_ALIASES: dict[str, list[str]] = {
    "PTT":    ["ปตท", "ปิโตรเลียมแห่งประเทศไทย", "บริษัท ปตท"],
    "KBANK":  ["กสิกรไทย", "ธนาคารกสิกรไทย", "แบงก์กสิกร"],
    "SCB":    ["ไทยพาณิชย์", "ธนาคารไทยพาณิชย์", "แบงก์ไทยพาณิชย์"],
    "BBL":    ["กรุงเทพ", "ธนาคารกรุงเทพ", "แบงก์กรุงเทพ"],
    "KTB":    ["กรุงไทย", "ธนาคารกรุงไทย", "แบงก์กรุงไทย"],
    "BAY":    ["กรุงศรี", "ธนาคารกรุงศรีอยุธยา", "กรุงศรีอยุธยา"],
    "ADVANC": ["ดีแทค", "แอดวานซ์", "เอไอเอส", "AIS"],
    "INTUCH": ["อินทัช", "ชินคอร์ป"],
    "TRUE":   ["ทรู", "ทรูมูฟ", "ทรูคอร์ป"],
    "DTAC":   ["ดีแทค", "โทเทิ่ล แอ็คเซ็ส"],
    "CPALL":  ["เซเว่น", "7-11", "ซีพีออลล์", "เซเว่นอีเลฟเว่น"],
    "CPF":    ["ซีพีเอฟ", "เจริญโภคภัณฑ์อาหาร", "ซีพีฟู้ด"],
    "CPN":    ["เซ็นทรัลพัฒนา", "เซ็นทรัล"],
    "MAKRO":  ["แม็คโคร", "สยามแม็คโคร"],
    "HMPRO":  ["โฮมโปร", "โฮม โปร"],
    "BJC":    ["เบอร์ลี่ ยุคเกอร์", "บีเจซี"],
    "MINT":   ["มายเนอร์", "ไมเนอร์ อินเตอร์เนชั่นแนล"],
    "ERW":    ["รอยัล ออคิด", "โรงแรม"],
    "CENTEL": ["เซ็นทารา", "โรงแรมเซ็นทารา"],
    "TOP":    ["ไทยออยล์", "Thai Oil"],
    "PTTGC":  ["พีทีทีจีซี", "จีซี", "GC"],
    "IRPC":   ["ไออาร์พีซี", "IRPC"],
    "BCP":    ["บางจาก", "บางจากปิโตรเลียม"],
    "SPRC":   ["ศรีราชา", "ไทยสตาร์ออยล์"],
    "PTTEP":  ["ปตท สผ", "พีทีทีอีพี", "สำรวจและผลิตปิโตรเลียม"],
    "RATCH":  ["ราช", "ราชบุรี", "ราชบุรีไฟฟ้า"],
    "EGCO":   ["ผลิตไฟฟ้า", "อีจีซีโอ"],
    "GULF":   ["กัลฟ์", "กัลฟ์ เอ็นเนอร์จี"],
    "BGRIM":  ["บี.กริม", "บีกริม"],
    "EA":     ["พลังงานบริสุทธิ์", "อีเอ"],
    "SCC":    ["ปูนซิเมนต์ไทย", "ซีเมนต์ไทย", "SCG"],
    "TISCO":  ["ทิสโก้", "ธนาคารทิสโก้"],
    "KKP":    ["เกียรตินาคิน", "ธนาคารเกียรตินาคิน"],
    "TCAP":   ["ธนชาต", "ธนาคารธนชาต"],
    "TMB":    ["ทหารไทย", "ธนาคารทหารไทย", "ทีเอ็มบี"],
    "BTS":    ["บีทีเอส", "รถไฟฟ้า", "สกาย"],
    "BEM":    ["ทางด่วน", "ทางด่วนและรถไฟฟ้า"],
    "AOT":    ["ท่าอากาศยาน", "สนามบิน", "ดอนเมือง", "สุวรรณภูมิ"],
    "THAI":   ["การบินไทย", "สายการบินไทย", "ไทยแอร์เวย์"],
    "AAV":    ["แอร์เอเชีย", "เอเชียเอวิเอชั่น"],
    "NOK":    ["นกแอร์", "สายการบินนก"],
    "WHA":    ["ดับบลิวเอชเอ", "นิคมอุตสาหกรรม"],
    "AMATA":  ["อมตะ", "นิคมอมตะ"],
    "IVL":    ["อินโดรามา", "ไฟเบอร์"],
    "TKN":    ["ทีเคเอ็น"],
    "DELTA":  ["เดลต้า"],
    "HANA":   ["ฮาน่า", "อิเล็กทรอนิกส์"],
    "KCE":    ["เคซีอี", "อิเล็กทรอนิกส์"],
    "BLAND":  ["แบล็นด์", "บริษัทบางกอกแลนด์"],
    "LH":     ["แลนด์แอนด์เฮาส์", "แลนด์ แอนด์ เฮ้าส์"],
}


def _fetch_csv_from_set() -> str | None:
    """Attempt to download the listed-companies CSV from set.or.th."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    for url in (SET_DOWNLOAD_URL, SET_CSV_URL):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            if resp.text.strip():
                logger.info("Downloaded ticker list from %s", url)
                return resp.text
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
    return None


def _is_html(raw: str) -> bool:
    """Return True if the response looks like an HTML page rather than CSV."""
    stripped = raw.lstrip()
    return stripped.startswith("<!") or stripped.lower().startswith("<html")


def _parse_set_csv(raw: str) -> list[dict[str, Any]]:
    """
    Parse the set.or.th CSV into a list of ticker dicts.

    The CSV format from set.or.th typically has columns:
    Symbol, Name, Market, Sector, Industry, ...
    Returns an empty list if the content is HTML (download page instead of data file).
    """
    if _is_html(raw):
        logger.warning("Downloaded content is HTML, not CSV — cannot parse ticker list")
        return []

    reader = csv.DictReader(StringIO(raw))
    rows: list[dict[str, Any]] = []

    # Normalise column names — SET changes header names occasionally
    col_map = {
        "symbol": "ticker",
        "name": "company_name_en",
        "market": "market",
        "sector": "sector",
    }

    for row in reader:
        normalised: dict[str, Any] = {}
        for src, dst in col_map.items():
            for key in row:
                if key is None:  # malformed CSV row
                    continue
                if key.strip().lower() == src:
                    val = row[key]
                    normalised[dst] = val.strip() if val else ""
                    break

        ticker = normalised.get("ticker", "").strip().upper()
        if not ticker or ticker.startswith("#"):
            continue

        rows.append(
            {
                "ticker": ticker,
                "company_name_th": None,  # not in SET CSV; enriched separately
                "company_name_en": normalised.get("company_name_en"),
                "sector": normalised.get("sector"),
                "market": normalised.get("market", "SET").upper(),
                "listed_date": None,
            }
        )
    return rows


def _load_local_csv() -> list[dict[str, Any]]:
    """Load tickers from the committed data/set_tickers.csv as a fallback."""
    if not TICKERS_CSV.exists():
        logger.warning("Local tickers CSV not found at %s", TICKERS_CSV)
        return []

    rows: list[dict[str, Any]] = []
    with TICKERS_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticker = row.get("ticker", "").strip().upper()
            if ticker:
                rows.append(
                    {
                        "ticker": ticker,
                        "company_name_th": row.get("company_name_th"),
                        "company_name_en": row.get("company_name_en"),
                        "sector": row.get("sector"),
                        "market": row.get("market", "SET").upper(),
                        "listed_date": row.get("listed_date") or None,
                    }
                )
    logger.info("Loaded %d tickers from local CSV", len(rows))
    return rows


def upsert_tickers(rows: list[dict[str, Any]]) -> int:
    """Upsert ticker rows into the DB, returns count inserted/updated."""
    sql = """
        INSERT INTO tickers (ticker, company_name_th, company_name_en, sector, market, listed_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            company_name_en = excluded.company_name_en,
            sector          = excluded.sector,
            market          = excluded.market,
            updated_at      = datetime('now')
    """
    data = [
        (
            r["ticker"],
            r.get("company_name_th"),
            r.get("company_name_en"),
            r.get("sector"),
            r.get("market"),
            r.get("listed_date"),
        )
        for r in rows
    ]
    with db_session() as db:
        db.executemany(sql, data)
    return len(data)


def refresh_tickers() -> int:
    """
    Main entry point: download SET ticker list, upsert into DB.
    Falls back to local CSV if download fails.
    """
    raw = _fetch_csv_from_set()
    rows: list[dict[str, Any]] = []
    if raw:
        rows = _parse_set_csv(raw)
    if not rows:
        logger.info("Remote CSV unavailable or unparseable — using local CSV")
        rows = _load_local_csv()

    if rows and raw and not _is_html(raw):
        # Save a fresh local copy for offline use
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with TICKERS_CSV.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["ticker", "company_name_th", "company_name_en", "sector", "market", "listed_date"],
            )
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Saved %d tickers to %s", len(rows), TICKERS_CSV)

    if not rows:
        logger.error("No ticker data available — aborting upsert")
        return 0

    count = upsert_tickers(rows)
    logger.info("Upserted %d tickers", count)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    refresh_tickers()
