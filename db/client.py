"""
Turso/LibSQL database client with local SQLite fallback.

Uses Turso's HTTP pipeline API (POST /v2/pipeline) directly via requests,
avoiding the libsql-client WebSocket compatibility issues.
Falls back to a local SQLite file when TURSO_URL is not set.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Sequence

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_TURSO_URL: str | None = os.getenv("TURSO_URL")
_TURSO_AUTH_TOKEN: str | None = os.getenv("TURSO_AUTH_TOKEN")
_LOCAL_DB_PATH = Path(__file__).parent.parent / "data" / "local_dev.db"
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _init_schema(conn: sqlite3.Connection) -> None:
    ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(ddl)
    conn.commit()


def _turso_http_url(libsql_url: str) -> str:
    """
    Convert libsql:// URL to the Turso HTTPS pipeline endpoint.
    e.g. libsql://my-db.turso.io → https://my-db.turso.io/v2/pipeline
    """
    url = libsql_url.replace("libsql://", "https://").rstrip("/")
    return f"{url}/v2/pipeline"


def _encode_value(v: Any) -> dict:
    """
    Encode a Python value to a Turso v2 pipeline arg object.

    Turso hrana v2 protocol:
      - integer → {"type": "integer", "value": "<str>"}  (string for 64-bit safety)
      - float   → {"type": "float",   "value": <number>} (JSON number, NOT string)
      - text    → {"type": "text",    "value": "<str>"}
      - null    → {"type": "null"}
    """
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": float(v)}   # must be JSON number
    return {"type": "text", "value": str(v)}


# ---------------------------------------------------------------------------
# Turso HTTP client
# ---------------------------------------------------------------------------

class TursoClient:
    """
    Synchronous Turso client using the HTTP pipeline API.

    Batches all statements in a single POST /v2/pipeline request.
    Initialises the schema on first use.
    """

    def __init__(self, url: str, token: str) -> None:
        self._endpoint = _turso_http_url(url)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._session = requests.Session()
        self._session.headers.update(self._headers)
        self._ensure_schema()

    def _pipeline(self, statements: list[dict]) -> list[dict]:
        """POST a pipeline request; return the list of result objects."""
        payload = {"requests": statements}
        resp = self._session.post(self._endpoint, json=payload, timeout=30)
        if not resp.ok:
            logger.error("Turso HTTP %s: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        # Check for errors in any result
        for i, result in enumerate(results):
            if result.get("type") == "error":
                raise RuntimeError(
                    f"Turso error on statement {i}: {result.get('error', {}).get('message')}"
                )
        return results

    def _ensure_schema(self) -> None:
        """Apply schema.sql statement-by-statement via individual pipeline calls."""
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        # Strip comment lines from each chunk then keep non-empty SQL statements
        raw_chunks = ddl.split(";")
        stmts: list[str] = []
        for chunk in raw_chunks:
            # Remove leading comment lines, keep the actual SQL
            lines = [
                line for line in chunk.splitlines()
                if line.strip() and not line.strip().startswith("--")
            ]
            sql = "\n".join(lines).strip()
            if sql:
                stmts.append(sql + ";")

        # Send each statement individually so a failure on one doesn't abort others
        for stmt in stmts:
            try:
                self._pipeline([{"type": "execute", "stmt": {"sql": stmt}}])
            except Exception as exc:
                logger.debug("Schema stmt skipped (%s): %.60s", exc, stmt)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        args = [_encode_value(v) for v in params]
        stmt: dict[str, Any] = {"sql": sql}
        if args:
            stmt["args"] = args
        self._pipeline([{"type": "execute", "stmt": stmt}])

    def executemany(self, sql: str, rows: list[Sequence[Any]], chunk_size: int = 100) -> None:
        if not rows:
            return
        # Turso's pipeline API has a per-request statement limit; chunk large batches
        for offset in range(0, len(rows), chunk_size):
            chunk = rows[offset : offset + chunk_size]
            requests_payload = [
                {
                    "type": "execute",
                    "stmt": {"sql": sql, "args": [_encode_value(v) for v in row]},
                }
                for row in chunk
            ]
            self._pipeline(requests_payload)

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        args = [_encode_value(v) for v in params]
        stmt: dict[str, Any] = {"sql": sql}
        if args:
            stmt["args"] = args
        results = self._pipeline([{"type": "execute", "stmt": stmt}])
        if not results:
            return []
        result = results[0]
        if result.get("type") != "ok":
            return []
        response = result.get("response", {})
        cols_meta = response.get("result", {}).get("cols", [])
        col_names = [c.get("name") for c in cols_meta]
        raw_rows = response.get("result", {}).get("rows", [])
        output = []
        for raw_row in raw_rows:
            row_dict: dict[str, Any] = {}
            for col, cell in zip(col_names, raw_row):
                cell_type = cell.get("type")
                cell_val = cell.get("value")
                if cell_type == "null":
                    row_dict[col] = None
                elif cell_type == "integer":
                    row_dict[col] = int(cell_val)
                elif cell_type == "float":
                    row_dict[col] = float(cell_val)
                else:
                    row_dict[col] = cell_val
            output.append(row_dict)
        return output

    def close(self) -> None:
        self._session.close()


# ---------------------------------------------------------------------------
# Local SQLite branch
# ---------------------------------------------------------------------------

class LocalSQLiteClient:
    """sqlite3-backed client matching the TursoClient interface."""

    def __init__(self, db_path: Path = _LOCAL_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(self._conn)
        logger.info("Using local SQLite at %s", db_path)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self._conn.execute(sql, params)
        self._conn.commit()

    def executemany(self, sql: str, rows: list[Sequence[Any]]) -> None:
        self._conn.executemany(sql, rows)
        self._conn.commit()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Public factory & context manager
# ---------------------------------------------------------------------------

def get_client() -> TursoClient | LocalSQLiteClient:
    """Return a database client based on available environment variables."""
    if _TURSO_URL and _TURSO_AUTH_TOKEN:
        logger.info("Connecting to Turso at %s", _TURSO_URL)
        return TursoClient(_TURSO_URL, _TURSO_AUTH_TOKEN)
    logger.warning("TURSO_URL/TURSO_AUTH_TOKEN not set — falling back to local SQLite")
    return LocalSQLiteClient()


@contextmanager
def db_session() -> Generator[TursoClient | LocalSQLiteClient, None, None]:
    """Context manager that opens and cleanly closes a DB client."""
    client = get_client()
    try:
        yield client
    finally:
        client.close()
