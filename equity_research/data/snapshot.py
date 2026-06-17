"""Snapshot utilities for the Phase 3D daily-refresh pipeline.

The batch script (scripts/batch_snapshot.py) runs the full research pipeline
for every watchlist ticker and writes the results to
``data/snapshots/latest.json``.  The API reads this file at startup and serves
watchlist tickers directly from it — eliminating the 10-20 s yfinance
round-trip for pre-computed names.

Staleness: a snapshot older than ``_MAX_AGE_HOURS`` (25 h) is not served, so a
missed nightly run degrades gracefully back to the live path rather than
serving yesterday's intrinsic values as if they were current.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = Path(__file__).parent.parent.parent / "data" / "snapshots" / "latest.json"
_MAX_AGE_HOURS: float = 25.0


def load_snapshot() -> dict:
    """Load the latest snapshot from disk.

    Returns an empty dict on any I/O or parse failure so callers can treat a
    missing snapshot as a cache miss without special-casing.
    """
    try:
        return json.loads(_SNAPSHOT_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Snapshot not loaded: %s", exc)
        return {}


def save_snapshot(tickers_dict: dict[str, dict], watchlist: list[str]) -> None:
    """Atomically write a new snapshot to disk.

    Args:
        tickers_dict: Mapping from ``TICKER.NS`` → full research dict.
        watchlist:    Ordered list of tickers included in this snapshot.
    """
    now_utc = datetime.datetime.utcnow()
    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = now_utc.replace(tzinfo=datetime.timezone.utc).astimezone(ist_offset)

    payload = {
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at_ist": now_ist.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
        "watchlist": watchlist,
        "ticker_count": len(tickers_dict),
        "tickers": tickers_dict,
    }

    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SNAPSHOT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(_SNAPSHOT_PATH)
    logger.info("Snapshot written: %d tickers → %s", len(tickers_dict), _SNAPSHOT_PATH)


def is_fresh(snapshot: dict, max_age_hours: float = _MAX_AGE_HOURS) -> bool:
    """Return True if the snapshot was generated within ``max_age_hours``."""
    gen_utc = snapshot.get("generated_at_utc", "")
    if not gen_utc:
        return False
    try:
        gen_dt = datetime.datetime.strptime(gen_utc, "%Y-%m-%dT%H:%M:%SZ")
        age_h = (datetime.datetime.utcnow() - gen_dt).total_seconds() / 3600
        return age_h < max_age_hours
    except ValueError:
        return False


def get_ticker_entry(snapshot: dict, ticker_ns: str) -> dict | None:
    """Return the snapshot entry for ``ticker_ns`` if the snapshot is fresh.

    Returns None when the snapshot is empty, stale, or does not contain the
    requested ticker — in all these cases the caller should fall through to a
    live fetch.
    """
    if not snapshot or not is_fresh(snapshot):
        return None
    return snapshot.get("tickers", {}).get(ticker_ns)
