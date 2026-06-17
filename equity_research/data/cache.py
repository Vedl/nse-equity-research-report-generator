"""JSON-file cache for market data — survives process restarts.

Cache key: ``{ticker}_{data_type}`` with a freshness timestamp inside the file.
TTLs per data type follow the project policy: 24 h for prices/profiles,
90 days for annual financials.

Storage location: ``CACHE_DIR`` env var, else ``data/cache/`` in the repo
(on Railway set ``CACHE_DIR=/tmp/cache`` — ephemeral but effective within a
deploy's lifetime).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "data" / "cache"

TTL_SECONDS = {
    "profile": 24 * 3600,          # 24 hours
    "prices": 24 * 3600,           # 24 hours
    "financials": 90 * 24 * 3600,  # 90 days (annual statements)
    "news": 24 * 3600,             # 24 hours (Phase 3C)
}


def _cache_dir() -> Path:
    d = Path(os.getenv("CACHE_DIR", str(_DEFAULT_DIR)))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", key)


def cache_path(key: str) -> Path:
    return _cache_dir() / f"{_safe_key(key)}.json"


def cache_entry_count() -> int:
    """Number of files currently in the cache (for /health)."""
    try:
        return sum(1 for _ in _cache_dir().glob("*.json"))
    except OSError:
        return 0


def get(key: str, data_type: str) -> dict | None:
    """Return the cached payload if present and fresh, else None."""
    path = cache_path(key)
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text())
        age = time.time() - float(envelope.get("ts", 0))
        ttl = TTL_SECONDS.get(data_type, 24 * 3600)
        if age > ttl:
            return None
        return envelope.get("payload")
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("Cache read failed for %s: %s", key, exc)
        return None


def put(key: str, payload: dict) -> None:
    """Write a payload with the current timestamp. Failures are non-fatal."""
    try:
        cache_path(key).write_text(json.dumps({"ts": time.time(), "payload": payload}))
    except (OSError, TypeError) as exc:
        logger.warning("Cache write failed for %s: %s", key, exc)


# --- DataFrame (de)serialisation helpers -----------------------------------


def df_to_payload(df: pd.DataFrame) -> dict:
    """Serialise a DataFrame, preserving a DatetimeIndex if present."""
    is_dt = isinstance(df.index, pd.DatetimeIndex)
    frame = df.copy()
    if is_dt:
        frame.index = frame.index.strftime("%Y-%m-%dT%H:%M:%S%z")
    return {"datetime_index": is_dt, "data": json.loads(frame.to_json(orient="split"))}


def payload_to_df(payload: dict) -> pd.DataFrame:
    data = payload.get("data", {})
    df = pd.DataFrame(
        data.get("data", []),
        index=data.get("index", []),
        columns=data.get("columns", []),
    )
    if payload.get("datetime_index"):
        df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    return df
