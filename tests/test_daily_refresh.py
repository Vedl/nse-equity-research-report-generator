"""Tests for Phase 3D: daily refresh + data provenance.

Covers:
  - Workflow YAML validity, cron schedule, loop-guard (no push trigger)
  - Snapshot freshness / staleness logic
  - Snapshot save + load round-trip
  - Provenance block correctness for full and short fundamental history
  - ``data_as_of`` and ``source`` keys present in every live response
  - AppConfig.watchlist populated from config.yaml
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(age_hours: float = 1.0, tickers: dict | None = None) -> dict:
    """Return a fake snapshot dict generated ``age_hours`` ago."""
    gen_utc = datetime.datetime.utcnow() - datetime.timedelta(hours=age_hours)
    ticker_data = tickers or {
        "HDFCBANK.NS": {
            "company": {"name": "HDFC Bank"},
            "data_as_of": "2026-06-17T03:30:00Z",
            "source": "snapshot",
        }
    }
    return {
        "generated_at_utc": gen_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at_ist": "2026-06-17T09:00:00+05:30",
        "watchlist": list(ticker_data.keys()),
        "ticker_count": len(ticker_data),
        "tickers": ticker_data,
    }


def _make_income(n_years: int, start_fy: int = 2024) -> pd.DataFrame:
    """Return a minimal income DataFrame with ``n_years`` rows."""
    years = list(range(start_fy - n_years + 1, start_fy + 1))
    return pd.DataFrame({"total_revenue": [100 * i for i in range(1, n_years + 1)]}, index=years)


# ---------------------------------------------------------------------------
# Workflow YAML
# ---------------------------------------------------------------------------


def test_workflow_yaml_exists():
    p = Path(__file__).parent.parent / ".github" / "workflows" / "daily-refresh.yml"
    assert p.exists(), "daily-refresh.yml not found in .github/workflows/"


def test_workflow_yaml_is_parseable():
    p = Path(__file__).parent.parent / ".github" / "workflows" / "daily-refresh.yml"
    doc = yaml.safe_load(p.read_text())
    assert isinstance(doc, dict)


def _workflow_doc() -> dict:
    """Load daily-refresh.yml. PyYAML (YAML 1.1) parses ``on:`` as the bool key ``True``."""
    p = Path(__file__).parent.parent / ".github" / "workflows" / "daily-refresh.yml"
    return yaml.safe_load(p.read_text())


def _on_block(doc: dict) -> dict:
    """Return the ``on:`` triggers block regardless of whether the key is 'on' or True."""
    return doc.get("on", doc.get(True, {})) or {}


def test_workflow_cron_is_0330_utc():
    doc = _workflow_doc()
    schedules = _on_block(doc).get("schedule", [])
    crons = [s["cron"] for s in schedules]
    assert "30 3 * * *" in crons, f"Expected cron '30 3 * * *', got {crons}"


def test_workflow_no_push_trigger():
    """Loop guard: committing the snapshot must not retrigger the workflow."""
    doc = _workflow_doc()
    triggers = set(_on_block(doc).keys())
    assert "push" not in triggers, "workflow 'on:' block must not include 'push'"


def test_workflow_has_contents_write():
    doc = _workflow_doc()
    perms = doc.get("permissions", {})
    assert perms.get("contents") == "write", (
        "workflow needs 'permissions: contents: write' to commit the snapshot"
    )


def test_workflow_has_workflow_dispatch():
    """workflow_dispatch allows manual runs without waiting for the cron."""
    doc = _workflow_doc()
    assert "workflow_dispatch" in _on_block(doc), (
        "workflow should support manual dispatch (workflow_dispatch)"
    )


# ---------------------------------------------------------------------------
# Snapshot freshness
# ---------------------------------------------------------------------------


def test_is_fresh_recent():
    from equity_research.data.snapshot import is_fresh
    assert is_fresh(_make_snapshot(age_hours=1.0)) is True


def test_is_fresh_exactly_at_boundary():
    from equity_research.data.snapshot import is_fresh
    assert is_fresh(_make_snapshot(age_hours=24.9)) is True


def test_is_fresh_stale():
    from equity_research.data.snapshot import is_fresh
    assert is_fresh(_make_snapshot(age_hours=26.0)) is False


def test_is_fresh_empty_dict():
    from equity_research.data.snapshot import is_fresh
    assert is_fresh({}) is False


def test_is_fresh_missing_timestamp():
    from equity_research.data.snapshot import is_fresh
    assert is_fresh({"tickers": {}}) is False


# ---------------------------------------------------------------------------
# Snapshot get_ticker_entry
# ---------------------------------------------------------------------------


def test_get_ticker_entry_fresh_hit():
    from equity_research.data.snapshot import get_ticker_entry
    snap = _make_snapshot(age_hours=1.0)
    entry = get_ticker_entry(snap, "HDFCBANK.NS")
    assert entry is not None
    assert entry["source"] == "snapshot"


def test_get_ticker_entry_stale_returns_none():
    from equity_research.data.snapshot import get_ticker_entry
    snap = _make_snapshot(age_hours=26.0)
    assert get_ticker_entry(snap, "HDFCBANK.NS") is None


def test_get_ticker_entry_unknown_ticker_returns_none():
    from equity_research.data.snapshot import get_ticker_entry
    snap = _make_snapshot(age_hours=1.0)
    assert get_ticker_entry(snap, "RELIANCE.NS") is None


def test_get_ticker_entry_empty_snapshot():
    from equity_research.data.snapshot import get_ticker_entry
    assert get_ticker_entry({}, "HDFCBANK.NS") is None


# ---------------------------------------------------------------------------
# Snapshot save + load round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    import equity_research.data.snapshot as snap_mod

    fake_path = tmp_path / "latest.json"
    monkeypatch.setattr(snap_mod, "_SNAPSHOT_PATH", fake_path)

    tickers_data = {
        "TCS.NS": {
            "company": {"name": "Tata Consultancy Services"},
            "data_as_of": "2026-06-17T03:30:00Z",
            "source": "snapshot",
        }
    }
    snap_mod.save_snapshot(tickers_data, ["TCS.NS"])

    loaded = snap_mod.load_snapshot()
    assert loaded["ticker_count"] == 1
    assert "TCS.NS" in loaded["tickers"]
    assert "generated_at_ist" in loaded
    assert "generated_at_utc" in loaded
    assert "+05:30" in loaded["generated_at_ist"], "IST timestamp must carry +05:30 offset"
    assert loaded["tickers"]["TCS.NS"]["source"] == "snapshot"


def test_save_snapshot_has_real_timestamp(tmp_path, monkeypatch):
    """generated_at_utc must be a real timestamp, not a placeholder."""
    import equity_research.data.snapshot as snap_mod

    monkeypatch.setattr(snap_mod, "_SNAPSHOT_PATH", tmp_path / "latest.json")
    snap_mod.save_snapshot({"X.NS": {"source": "snapshot"}}, ["X.NS"])

    loaded = snap_mod.load_snapshot()
    gen = loaded["generated_at_utc"]
    # Must parse as ISO UTC
    dt = datetime.datetime.strptime(gen, "%Y-%m-%dT%H:%M:%SZ")
    age_seconds = abs((datetime.datetime.utcnow() - dt).total_seconds())
    assert age_seconds < 60, f"Snapshot timestamp is {age_seconds:.0f}s old — expected < 60s"


def test_load_snapshot_missing_file(tmp_path, monkeypatch):
    import equity_research.data.snapshot as snap_mod

    monkeypatch.setattr(snap_mod, "_SNAPSHOT_PATH", tmp_path / "nonexistent.json")
    result = snap_mod.load_snapshot()
    assert result == {}


# ---------------------------------------------------------------------------
# Provenance — full and short history
# ---------------------------------------------------------------------------


def test_provenance_five_fy_no_disclosures():
    from equity_research.analysis.provenance import build_provenance

    income = _make_income(5, start_fy=2024)
    empty = pd.DataFrame(index=income.index)
    profile = {"forward_eps": 50.0, "numberOfAnalystOpinions": 28}

    prov = build_provenance(
        ticker="TCS.NS", income=income, balance=empty,
        cashflow=empty, profile=profile, news_result=None
    )

    assert prov["fundamentals"]["fiscal_years_available"] == 5
    assert prov["fundamentals"]["fy_range"] == "FY20–FY24"
    assert prov["fundamentals"]["as_of_fy"] == 2024
    assert prov["forward_estimates"]["forward_eps_available"] is True
    assert prov["forward_estimates"]["analyst_count"] == 28
    # No window shortfall at 5 FY
    assert prov["disclosures"] == []


def test_provenance_short_history_has_disclosure():
    """2 FY triggers a disclosure about the 3y-CAGR window mismatch."""
    from equity_research.analysis.provenance import build_provenance

    income = _make_income(2, start_fy=2024)
    empty = pd.DataFrame(index=income.index)

    prov = build_provenance(
        ticker="NEWCO.NS", income=income, balance=empty,
        cashflow=empty, profile={}, news_result=None
    )

    assert prov["fundamentals"]["fiscal_years_available"] == 2
    assert len(prov["disclosures"]) >= 1
    all_text = " ".join(prov["disclosures"]).lower()
    assert "window" in all_text or "fy" in all_text or "year" in all_text


def test_provenance_four_fy_has_disclosure():
    """4 FY triggers a disclosure about 5y-average computations."""
    from equity_research.analysis.provenance import build_provenance

    income = _make_income(4, start_fy=2024)
    empty = pd.DataFrame(index=income.index)

    prov = build_provenance(
        ticker="MID.NS", income=income, balance=empty,
        cashflow=empty, profile={"forward_eps": 30.0}, news_result=None
    )

    assert prov["fundamentals"]["fiscal_years_available"] == 4
    assert len(prov["disclosures"]) >= 1


def test_provenance_empty_income():
    from equity_research.analysis.provenance import build_provenance

    prov = build_provenance(
        ticker="EMPTY.NS",
        income=pd.DataFrame(), balance=pd.DataFrame(),
        cashflow=pd.DataFrame(), profile={}, news_result=None,
    )

    assert prov["fundamentals"]["fiscal_years_available"] == 0
    assert prov["fundamentals"]["fy_range"] == "n/a"
    assert len(prov["disclosures"]) >= 1


def test_provenance_news_populated():
    from equity_research.analysis.provenance import build_provenance
    from equity_research.data.news import NewsItem, NewsSentimentResult

    income = _make_income(3, start_fy=2024)
    empty = pd.DataFrame(index=income.index)

    news = NewsSentimentResult(
        headlines=[NewsItem(title="T", source="S", published="2026-06-17", link="")],
        limited_coverage=False,
        polarity=0.1,
        sentiment_label="Mildly positive",
        pos_words=[], neg_words=[], carried_pct=0.5,
        sourced_at="2026-06-17T05:00:00Z",
    )

    prov = build_provenance(
        ticker="TEST.NS", income=income, balance=empty,
        cashflow=empty, profile={}, news_result=news,
    )

    assert prov["news"]["headline_count"] == 1
    assert prov["news"]["sourced_at"] == "2026-06-17T05:00:00Z"
    assert prov["news"]["source"] == "Google News RSS"


def test_provenance_no_news_result():
    from equity_research.analysis.provenance import build_provenance

    prov = build_provenance(
        ticker="TEST.NS",
        income=_make_income(3, start_fy=2024),
        balance=pd.DataFrame(),
        cashflow=pd.DataFrame(),
        profile={},
        news_result=None,
    )
    assert prov["news"]["headline_count"] == 0
    assert prov["news"]["sourced_at"] is None


def test_provenance_required_keys():
    """Provenance must always carry the four top-level keys."""
    from equity_research.analysis.provenance import build_provenance

    prov = build_provenance(
        ticker="ANY.NS",
        income=pd.DataFrame(),
        balance=pd.DataFrame(),
        cashflow=pd.DataFrame(),
        profile={},
        news_result=None,
    )
    for key in ("fundamentals", "forward_estimates", "news", "disclosures"):
        assert key in prov, f"Missing provenance key: {key}"


def test_provenance_actual_cagr_window_labelled():
    """actual_cagr_window_years must reflect the data actually present."""
    from equity_research.analysis.provenance import build_provenance

    # 2 FY → 1-year change, not a 3y CAGR
    income = _make_income(2, start_fy=2024)
    prov = build_provenance(
        ticker="X.NS", income=income, balance=pd.DataFrame(),
        cashflow=pd.DataFrame(), profile={}, news_result=None,
    )
    assert prov["fundamentals"]["actual_cagr_window_years"] == 1
    assert prov["fundamentals"]["intended_cagr_window_years"] == 3


# ---------------------------------------------------------------------------
# Config — watchlist
# ---------------------------------------------------------------------------


def test_config_has_watchlist_field():
    from equity_research.config import load_config
    cfg = load_config()
    assert hasattr(cfg, "watchlist"), "AppConfig must have a 'watchlist' field"
    assert isinstance(cfg.watchlist, list)


def test_config_watchlist_contains_banks():
    from equity_research.config import load_config
    cfg = load_config()
    assert len(cfg.watchlist) >= 5, "Watchlist should have at least the 5 main banks"
    assert "HDFCBANK" in cfg.watchlist
    assert "TCS" in cfg.watchlist


def test_config_yaml_has_watchlist_section():
    p = Path(__file__).parent.parent / "config.yaml"
    raw = yaml.safe_load(p.read_text())
    assert "watchlist" in raw, "config.yaml must have a 'watchlist' key"
    assert len(raw["watchlist"]) >= 5


# ---------------------------------------------------------------------------
# data_as_of + source: structural checks without live yfinance
# ---------------------------------------------------------------------------


def test_provenance_returns_json_serialisable():
    """All provenance values must be JSON-serialisable (no numpy, no datetime objects)."""
    from equity_research.analysis.provenance import build_provenance

    income = _make_income(4, start_fy=2024)
    prov = build_provenance(
        ticker="TCS.NS",
        income=income,
        balance=pd.DataFrame(index=income.index),
        cashflow=pd.DataFrame(index=income.index),
        profile={"forward_eps": 50.0, "numberOfAnalystOpinions": 25},
        news_result=None,
    )
    # If this raises, a value is not serialisable
    serialised = json.dumps(prov)
    loaded = json.loads(serialised)
    assert loaded["fundamentals"]["fiscal_years_available"] == 4
