#!/usr/bin/env python3
"""Batch snapshot builder — Phase 3D Part 1.

Runs the full research pipeline for every watchlist ticker defined in
config.yaml and writes the results to data/snapshots/latest.json.

Invoked by .github/workflows/daily-refresh.yml at 03:30 UTC.  Can also be
run manually:

    python scripts/batch_snapshot.py

Each ticker is processed independently; a failure on one does not abort
the others.  Successful results are collected and written as a single
atomic JSON file.  Railway auto-redeploys on push to main, so the next
request after a Railway start-up serves the fresh snapshot.

Importing ``main`` here loads the same config + provider singletons the
FastAPI server uses, so the snapshot format is byte-for-byte identical to
what the live ``/api/research/{ticker}`` endpoint returns.  The batch
script then overwrites ``source`` to ``"snapshot"`` before writing.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Ensure the repo root is importable before touching anything else.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("batch_snapshot")

# Importing ``main`` creates the FastAPI app object and loads config + provider
# singletons but does NOT start the HTTP server (uvicorn is not invoked here).
import main as _app_module  # noqa: E402

from equity_research.data.snapshot import save_snapshot  # noqa: E402

cfg = _app_module._config
watchlist_base: list[str] = cfg.watchlist

if not watchlist_base:
    logger.error("config.yaml has no 'watchlist' entries — nothing to snapshot.")
    sys.exit(1)

watchlist_ns: list[str] = [
    t if t.upper().endswith(".NS") else f"{t.upper()}.NS"
    for t in watchlist_base
]

logger.info("Watchlist: %d tickers", len(watchlist_ns))

results: dict[str, dict] = {}
skipped: list[tuple[str, str]] = []   # (ticker_ns, reason)

for ticker_ns in watchlist_ns:
    t0 = time.monotonic()
    try:
        data = _app_module._build_research(ticker_ns)
        data["source"] = "snapshot"   # override "live" set by _build_research
        results[ticker_ns] = data
        elapsed = time.monotonic() - t0
        logger.info("  OK   %-20s  (%.1f s)", ticker_ns, elapsed)
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {exc}"
        skipped.append((ticker_ns, reason))
        logger.warning("  SKIP %-20s — %s", ticker_ns, reason)

# ── Post-run summary (always logged — a missing name is a demo failure) ──────
n_ok = len(results)
n_skip = len(skipped)
n_total = len(watchlist_ns)
logger.info("=" * 60)
logger.info("Snapshot result: %d / %d succeeded, %d skipped", n_ok, n_total, n_skip)
if skipped:
    logger.warning("SKIPPED tickers (will fall through to live fetch on API):")
    for t, reason in skipped:
        logger.warning("  ✗ %-20s  %s", t, reason)
else:
    logger.info("All watchlist tickers succeeded — snapshot is complete.")
logger.info("=" * 60)

if not results:
    logger.error("All %d tickers failed — aborting snapshot write.", n_total)
    sys.exit(1)

save_snapshot(results, watchlist_ns)
logger.info("Snapshot written with %d entries.", n_ok)
if n_skip > 0:
    # Exit non-zero so GH Actions marks the step as warning (yellow), not green.
    # The snapshot is still written with the successful entries.
    sys.exit(2)
