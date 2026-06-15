"""FastAPI application — Equity Research Report Generator.

Four endpoints:
  GET /api/health                → {"status": "ok"}
  GET /api/tickers               → list of {ticker, name, sector}
  GET /api/research/{ticker}     → full JSON research dict
  GET /api/report/{ticker}/pdf   → downloadable PDF file

Architecture notes
------------------
* Module-level singletons for config + provider — loaded once at startup.
* /api/research and /api/report use plain ``def`` (not ``async def``) so FastAPI
  dispatches them to the default threadpool.  yfinance calls and WeasyPrint are
  synchronous; making them ``async def`` would block the event loop.
* An in-memory TTLCache (30 min) wraps the assembled research dict so repeated
  requests for the same ticker skip the 10–20 s yfinance round-trip.  The PDF
  endpoint reuses that cache before calling the report builder.
* CORS origin(s) read from ALLOWED_ORIGINS env var (comma-separated); defaults
  to "*" for local development.
* slowapi rate-limiter (10 req/min/IP) on the two heavy endpoints to protect
  against yfinance IP bans from a public Railway URL.
"""

from __future__ import annotations

import logging
import math
import os
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread

import pandas as pd
from cachetools import TTLCache
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from equity_research.analysis.pipeline import ResearchBundle, run_research_pipeline
from equity_research.analysis.ratios import compute_ratios
from equity_research.config import load_config
from equity_research.data import cache as file_cache
from equity_research.data.yfinance_provider import YFinanceProvider
from equity_research.report.builder import generate_report
from equity_research.backtest import run_backtest
import dataclasses
import json

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (initialised once at process start)
# ---------------------------------------------------------------------------

_config = load_config()
_provider = YFinanceProvider(_config)

_NIFTY500_CSV = Path(__file__).parent / "equity_research" / "data" / "nifty500_tickers.csv"
_nifty500_df: pd.DataFrame = pd.read_csv(_NIFTY500_CSV, dtype=str).fillna("")

# ticker → company_name lookup (upper-cased keys for case-insensitive match)
_TICKER_NAME: dict[str, str] = dict(
    zip(_nifty500_df["ticker"].str.upper(), _nifty500_df["company_name"])
)

# Master universe with valuation families (built by scripts/build_universe.py)
_UNIVERSE_JSON = Path(__file__).parent / "data" / "company_universe.json"
try:
    _universe: dict[str, dict] = json.loads(_UNIVERSE_JSON.read_text())
except (OSError, json.JSONDecodeError):
    logger.warning("company_universe.json missing — run scripts/build_universe.py")
    _universe = {}

_REPORT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", _config.report.output_dir))

# ---------------------------------------------------------------------------
# Rate limiter + cache
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

# TTL = 1 800 s (30 min).  Yahoo data freshness is good enough at this cadence.
_research_cache: TTLCache = TTLCache(maxsize=128, ttl=1800)
_backtest_cache: TTLCache = TTLCache(maxsize=1, ttl=86400)

# ---------------------------------------------------------------------------
# Startup pre-warm
# ---------------------------------------------------------------------------

_PREWARM_TICKERS: list[str] = []


def _prewarm_cache() -> None:
    """Pre-fetch and cache research data for featured tickers at startup.

    Runs in a daemon background thread so it never blocks the server from
    accepting requests.  Each ticker is fetched independently; a failure on
    one does not affect the others.
    """
    for raw_ticker in _PREWARM_TICKERS:
        ticker_ns = _normalize_ticker(raw_ticker)
        try:
            result = _build_research(ticker_ns)
            _research_cache[ticker_ns] = result   # manual write required — _build_research
            logger.info("cache warm: %s", ticker_ns)  # has no @cached decorator
        except Exception as exc:  # noqa: BLE001
            logger.warning("pre-warm failed for %s: %s", ticker_ns, exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    Thread(target=_prewarm_cache, daemon=True).start()
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Equity Research Report Generator",
    description="Real-data equity research for Nifty 500 companies.",
    version="1.0.0",
    lifespan=_lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_ticker(ticker: str) -> str:
    """Return the NSE ticker with a .NS suffix, upper-cased."""
    t = ticker.upper().strip()
    return t if t.endswith(".NS") else f"{t}.NS"


def _clean(value: object) -> float | None:
    """Coerce a value to a Python float, returning None for NaN / inf / non-numeric."""
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _df_to_records(df: pd.DataFrame, col_map: dict[str, str]) -> list[dict]:
    """Convert a normalised financial DataFrame to a list of row dicts.

    Args:
        df:      DataFrame with integer year as index and snake_case columns.
        col_map: Mapping from DataFrame column name → desired output key.

    Returns:
        List of dicts with ``year`` plus one key per col_map entry.
        Missing columns and NaN values both surface as ``None``.
    """
    records: list[dict] = []
    for year, row in df.iterrows():
        entry: dict = {"year": int(year)}
        for src, dst in col_map.items():
            entry[dst] = _clean(row.get(src))
        records.append(entry)
    return records


def _get_price_change(ticker_ns: str) -> tuple[float | None, float | None]:
    """Return (absolute_change, pct_change) over the last two trading sessions.

    Returns (None, None) on any failure — missing data is logged, not raised.
    """
    try:
        prices = _provider.get_prices(ticker_ns, period="5d")
        if prices.empty:
            return None, None
        closes = prices["Close"].dropna()
        if len(closes) < 2:
            return None, None
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        change = last - prev
        pct = (change / prev) if prev != 0.0 else None
        return change, pct
    except Exception:  # noqa: BLE001
        logger.warning("Price-change fetch failed for %s", ticker_ns)
        return None, None


def _get_usdinr() -> float:
    """Return USD/INR rate for market-cap conversion.

    Delegates to the shared ``_fetch_usdinr`` helper in yfinance_provider,
    which applies a (75–92) plausibility filter and tries multiple sources
    (fast_info, info dict, 5-day history, inverse pair) before falling back
    to the config value.
    """
    from equity_research.data.yfinance_provider import _fetch_usdinr
    return _fetch_usdinr(_config.market.fallback_usd_inr)




def _build_research(ticker_ns: str) -> dict:
    """Fetch data, run full analysis, and assemble the API response dict.

    This is the core orchestration function called by both the research and
    report endpoints.  It raises HTTPException(404) if yfinance returns no
    data for the ticker; all other failures propagate as plain exceptions to
    be caught by the endpoint handler.
    """
    t0 = time.monotonic()
    logger.info("Building research for %s", ticker_ns)

    # ── Fetch ────────────────────────────────────────────────────────────────
    profile = _provider.get_profile(ticker_ns)
    if not profile.get("long_name"):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No data returned for '{ticker_ns}'. "
                "Verify the ticker is in the Nifty 500 and yfinance has coverage."
            ),
        )

    financials = _provider.get_financials(ticker_ns)
    income = financials["income"]
    balance = financials["balance_sheet"]
    cashflow = financials["cash_flow"]

    # ── Analysis ─────────────────────────────────────────────────────────────
    ratios = compute_ratios(
        income,
        balance,
        cashflow,
        tax_rate=_config.market.tax_rate,
    )

    # ── Full research pipeline: beta → valuation → quality → conviction ──
    bundle = run_research_pipeline(profile, financials, _provider, _config)
    val_result = bundle.valuation

    # ── Price change (supplementary fetch) ────────────────────────────────
    change, change_pct = _get_price_change(ticker_ns)

    # ── Currency conversion ───────────────────────────────────────────────
    market_cap = _clean(profile.get("market_cap"))
    usdinr = _get_usdinr()   # always a float — never None
    market_cap_usd = _clean(market_cap / usdinr) if market_cap else None

    # ── Assemble response ────────────────────────────────────────────────
    company = {
        "name":        profile.get("long_name"),
        "ticker":      profile.get("ticker"),
        "sector":      profile.get("sector"),
        "industry":    profile.get("industry"),
        "description": profile.get("long_business_summary"),
    }

    price_section = {
        "current":        _clean(profile.get("current_price")),
        "change":         _clean(change),
        "change_pct":     _clean(change_pct),
        "week_52_low":    _clean(profile.get("fifty_two_week_low")),
        "week_52_high":   _clean(profile.get("fifty_two_week_high")),
        "market_cap":     market_cap,
        "market_cap_usd": market_cap_usd,
    }

    income_records = _df_to_records(income, {
        "total_revenue":    "revenue",
        "gross_profit":     "gross_profit",
        "operating_income": "operating_income",
        "net_income":       "net_income",
        "basic_eps":        "eps",
    })
    balance_records = _df_to_records(balance, {
        "total_assets":        "total_assets",
        "total_debt":          "total_debt",
        "stockholders_equity": "equity",
        "cash_and_equivalents":"cash",
    })
    cashflow_records = _df_to_records(cashflow, {
        "operating_cash_flow": "operating_cf",
        "capital_expenditure": "capex",
        "free_cash_flow":      "free_cash_flow",
    })

    # Flatten nested ratios dict
    p   = ratios.get("profitability", {})
    liq = ratios.get("liquidity", {})
    sol = ratios.get("solvency", {})
    eff = ratios.get("efficiency", {})
    cg  = ratios.get("cagr", {})
    ratios_out = {
        "gross_margin":      _clean(p.get("gross_margin")),
        "operating_margin":  _clean(p.get("operating_margin")),
        "net_margin":        _clean(p.get("net_margin")),
        "roe":               _clean(p.get("roe")),
        "roic":              _clean(p.get("roic")),
        "current_ratio":     _clean(liq.get("current_ratio")),
        "quick_ratio":       _clean(liq.get("quick_ratio")),
        "debt_equity":       _clean(sol.get("debt_to_equity")),
        "interest_coverage": _clean(sol.get("interest_coverage")),
        "asset_turnover":    _clean(eff.get("asset_turnover")),
        "revenue_cagr_3y":   _clean(cg.get("revenue_3y")),
        "eps_cagr_3y":       _clean(cg.get("eps_3y")),
    }

    # ── Build valuation response section ──────────────────────────────────

    def _pct_str_to_float(s: str) -> float:
        return round(float(s.rstrip("%")) / 100, 4)

    # DCF sub-section (only when FCFF was the routed model)
    dcf_out: dict | None = None
    if val_result.dcf_result is not None:
        dr = val_result.dcf_result
        sensitivity_rows: list[list[float | None]] = [
            [_clean(v) for v in row]
            for _, row in dr.sensitivity.iterrows()
        ]
        dcf_out = {
            "intrinsic_value": _clean(dr.intrinsic_value_per_share),
            "sensitivity":     sensitivity_rows,
            "sensitivity_wacc_labels": [
                _pct_str_to_float(s) for s in dr.sensitivity.index.tolist()
            ],
            "sensitivity_tg_labels": [
                _pct_str_to_float(s) for s in dr.sensitivity.columns.tolist()
            ],
            "base_fcff":          _clean(dr.base_fcff),
            "growth_rate":        _clean(dr.growth_rate),
            "net_debt":           _clean(dr.net_debt),
            "shares_outstanding": _clean(dr.shares_outstanding),
            "assumptions": {
                "wacc":            _clean(dr.wacc),
                "terminal_growth": _clean(dr.terminal_growth),
                "projection_years": _config.dcf.projection_horizon,
                "risk_free_rate":   _config.market.risk_free_rate,
                "erp":              _config.market.equity_risk_premium,
            },
        }

    # Residual Income sub-section
    ri_out: dict | None = None
    if val_result.ri_result is not None:
        ri = val_result.ri_result
        ri_out = {
            "intrinsic_value":       _clean(ri.intrinsic_value_per_share),
            "book_value_per_share":  _clean(ri.book_value_per_share),
            "cost_of_equity":        _clean(ri.cost_of_equity),
            "growth_rate":           _clean(ri.growth_rate),
            "terminal_growth":       _clean(ri.terminal_growth),
            "shares_outstanding":    _clean(ri.shares_outstanding),
        }

    # Excess Return sub-section
    er_out: dict | None = None
    if val_result.excess_return_result is not None:
        er = val_result.excess_return_result
        er_out = {
            "intrinsic_value":       _clean(er.intrinsic_value_per_share),
            "book_value_per_share":  _clean(er.book_value_per_share),
            "cost_of_equity":        _clean(er.cost_of_equity),
            "roe":                   _clean(er.roe),
            "sustainable_growth":    _clean(er.sustainable_growth),
            "terminal_growth":       _clean(er.terminal_growth),
            "shares_outstanding":    _clean(er.shares_outstanding),
            "is_pb_fallback":        er.is_pb_fallback,
        }

    # Relative valuation range
    relative_out: dict | None = None
    if val_result.relative is not None:
        rel = val_result.relative
        relative_out = {
            "low":               _clean(rel.low),
            "high":              _clean(rel.high),
            "median":            _clean(rel.median),
            "implied_pe":        _clean(rel.implied_pe),
            "implied_ev_ebitda": _clean(rel.implied_ev_ebitda),
            "implied_pb":        _clean(rel.implied_pb),
            "implied_ev_sales":  _clean(rel.implied_ev_sales),
        }

    # India Valuation adjustments
    india_out: dict | None = None
    if val_result.india_result is not None:
        india = val_result.india_result
        india_out = {
            "primary_multiple": india.primary_multiple,
            "sector_note": india.sector_note,
            "is_psu": india.is_psu,
            "psu_discount_pct": _clean(india.psu_discount_pct),
            "promoter_score": _clean(india.promoter_score),
            "promoter_premium_pct": _clean(india.promoter_premium_pct),
            "promoter_flags": india.promoter_flags,
            "group_adjustment_pct": _clean(india.group_adjustment_pct),
            "earnings_quality_score": _clean(india.earnings_quality_score),
            "accruals_ratio": _clean(india.accruals_ratio),
            "cfo_ebitda_ratio": _clean(india.cfo_ebitda_ratio),
            "earnings_quality_flags": india.earnings_quality_flags,
            "implied_revenue_cagr": _clean(india.implied_revenue_cagr),
            "dcf_vs_price_gap_pct": _clean(india.dcf_vs_price_gap_pct),
            "adjusted_dcf_value": _clean(india.adjusted_dcf_value),
            "blended_value": _clean(india.blended_value),
            "blended_upside_pct": _clean(india.blended_upside_pct),
            "narrative_bullets": india.narrative_bullets,
            "diverges_materially": india.diverges_materially,
        }

    # Financial sector (Justified P/B) sub-section
    financial_out: dict | None = None
    if val_result.financial_result is not None:
        fin = val_result.financial_result
        bm = fin.bank_metrics
        financial_out = {
            "justified_pb":          _clean(fin.justified_pb),
            "intrinsic_value":       _clean(fin.intrinsic_value_per_share),
            "book_value_per_share":  _clean(fin.book_value_per_share),
            "cost_of_equity":        _clean(fin.cost_of_equity),
            "roe":                   _clean(fin.roe),
            "growth_rate":           _clean(fin.growth_rate),
            "retention_ratio":       _clean(fin.retention_ratio),
            "roe_ke_spread":         _clean(fin.roe_ke_spread),
            "shares_outstanding":    _clean(fin.shares_outstanding),
            "sensitivity_roe_labels": fin.sensitivity_roe_labels,
            "sensitivity_ke_labels":  fin.sensitivity_ke_labels,
            "sensitivity_pb":         fin.sensitivity_pb,
            "is_fallback":           fin.is_fallback,
            "fallback_note":         fin.fallback_note,
            "bank_metrics": {
                "net_interest_margin": _clean(bm.net_interest_margin),
                "gross_npa_ratio":     _clean(bm.gross_npa_ratio),
                "credit_cost":         _clean(bm.credit_cost),
                "casa_ratio":          _clean(bm.casa_ratio),
                "tier1_ratio":         _clean(bm.tier1_ratio),
            },
        }

    # SOTP sub-section
    sotp_out: dict | None = None
    if val_result.sotp_result is not None:
        sotp = val_result.sotp_result
        sotp_out = {
            "total_ebitda":           _clean(sotp.total_ebitda),
            "total_ev":              _clean(sotp.total_ev),
            "net_debt":              _clean(sotp.net_debt),
            "equity_value":          _clean(sotp.equity_value),
            "shares_outstanding":    _clean(sotp.shares_outstanding),
            "intrinsic_value":       _clean(sotp.intrinsic_value_per_share),
            "blended_ev_ebitda":     _clean(sotp.blended_ev_ebitda),
            "is_fallback":           sotp.is_fallback,
            "fallback_note":         sotp.fallback_note,
            "segments": [
                {
                    "name":               seg.name,
                    "ebitda_share":       _clean(seg.ebitda_share),
                    "ev_ebitda_multiple": _clean(seg.ev_ebitda_multiple),
                    "segment_ebitda":    _clean(seg.segment_ebitda),
                    "segment_ev":        _clean(seg.segment_ev),
                    "note":              seg.note,
                }
                for seg in sotp.segments
            ],
        }

    # Path-to-breakeven (loss-making startups)
    breakeven_out: dict | None = None
    if val_result.path_to_breakeven is not None:
        ptb = val_result.path_to_breakeven
        breakeven_out = {
            "cash_runway_quarters":  _clean(ptb.cash_runway_quarters),
            "breakeven_revenue":     _clean(ptb.breakeven_revenue),
            "current_revenue":       _clean(ptb.current_revenue),
            "gap_to_breakeven_pct":  _clean(ptb.gap_to_breakeven_pct),
            "gross_margin":          _clean(ptb.gross_margin),
        }

    # Comps peer table
    comps_out: list[dict] = []
    if val_result.comps_result is not None:
        for pm in val_result.comps_result.peers:
            upper = pm.ticker.upper()
            comps_out.append({
                "ticker":    pm.ticker,
                "name":      _TICKER_NAME.get(upper, pm.ticker),
                "pe":        _clean(pm.pe),
                "ev_ebitda": _clean(pm.ev_ebitda),
                "pb":        _clean(pm.pb),
                "ev_sales":  _clean(pm.ev_sales),
            })

    # ── Quality & conviction sections (Phase 2 modules) ───────────────────
    c = bundle.conviction
    conviction_out = {
        "rating":            c.rating,
        "target_price":      _clean(c.target_price),
        "upside_pct":        _clean(c.upside_pct),
        "bear_value":        _clean(c.bear_value),
        "bull_value":        _clean(c.bull_value),
        "primary_model":     c.primary_model,
        "primary_value":     _clean(c.primary_value),
        "secondary_model":   c.secondary_model,
        "secondary_value":   _clean(c.secondary_value),
        "blended_value":     _clean(c.blended_value),
        "confidence_score":  c.confidence_score,
        "confidence_components": [
            {"name": x.name, "points": x.points, "max_points": x.max_points, "detail": x.detail}
            for x in c.confidence_components
        ],
        "models_agree":      c.models_agree,
        "beta":              _clean(bundle.beta.beta),
        "beta_source":       bundle.beta.source,
        "beta_months":       bundle.beta.months,
    }

    quality_out = {
        "piotroski": {
            "score": bundle.piotroski.score,
            "max_available": bundle.piotroski.max_available,
            "verdict": bundle.piotroski.verdict,
            "signals": [
                {"code": s.code, "name": s.name, "passed": s.passed, "detail": s.detail}
                for s in bundle.piotroski.signals
            ],
        },
        "beneish": {
            "m_score": _clean(bundle.beneish.m_score),
            "flagged": bundle.beneish.flagged,
            "missing": bundle.beneish.missing,
            "variables": {k: _clean(v) for k, v in bundle.beneish.variables.items()},
        },
        "altman": {
            "z_score": _clean(bundle.altman.z_score),
            "zone": bundle.altman.zone,
            "applicable": bundle.altman.applicable,
        },
        "accruals": {
            "accruals_ratio": _clean(bundle.accruals.accruals_ratio_cf),
            "cfo_ebitda": _clean(bundle.accruals.cfo_ebitda),
            "cfo_ni_series": [
                {"year": y, "ratio": _clean(r)} for y, r in bundle.accruals.cfo_ni_series
            ],
            "flags": bundle.accruals.flags,
        },
        "earnings_quality": {
            "verdict": bundle.earnings_quality.verdict,
            "verdict_reason": bundle.earnings_quality.verdict_reason,
            "quality_score": _clean(bundle.earnings_quality.quality_score),
            "sector": bundle.earnings_quality.sector,
            "peer_sample_size": bundle.earnings_quality.peer_sample_size,
            "accrual_sector_percentile": _clean(bundle.earnings_quality.accrual_sector_percentile),
            "fscore_sector_percentile": _clean(bundle.earnings_quality.fscore_sector_percentile),
            "components": [
                {
                    "key": c.key,
                    "name": c.name,
                    "flag": c.flag,
                    "metric": _clean(c.metric),
                    "reason": c.reason,
                }
                for c in bundle.earnings_quality.components
            ],
            "accruals": {
                "noa_latest": _clean(bundle.earnings_quality.accruals.noa_latest),
                "noa_prior": _clean(bundle.earnings_quality.accruals.noa_prior),
                "avg_total_assets": _clean(bundle.earnings_quality.accruals.avg_total_assets),
                "bs_accrual_ratio": _clean(bundle.earnings_quality.accruals.bs_accrual_ratio),
                "cf_accrual_ratio": _clean(bundle.earnings_quality.accruals.cf_accrual_ratio),
                "headline_ratio": _clean(bundle.earnings_quality.accruals.headline_ratio),
                "flag": bundle.earnings_quality.accruals.flag,
            },
            "warnings": bundle.earnings_quality.warnings,
        },
        "dupont": [
            {
                "year": y.year,
                "tax_burden": _clean(y.tax_burden),
                "interest_burden": _clean(y.interest_burden),
                "ebit_margin": _clean(y.ebit_margin),
                "asset_turnover": _clean(y.asset_turnover),
                "leverage": _clean(y.leverage),
                "roe": _clean(y.roe),
            }
            for y in bundle.dupont.years
        ],
        "gross_profitability": {
            "latest": _clean(bundle.gross_profitability.latest),
            "series": [
                {"year": y, "gpa": _clean(v)} for y, v in bundle.gross_profitability.series
            ],
        },
        "caq": {
            "score": bundle.caq.score,
            "max_score": bundle.caq.max_score,
            "components": [
                {"name": x.name, "points": x.points, "available": x.available, "detail": x.detail}
                for x in bundle.caq.components
            ],
        },
        "ccc": {
            "years": bundle.ccc.years,
            "dso": [_clean(v) for v in bundle.ccc.dso],
            "dio": [_clean(v) for v in bundle.ccc.dio],
            "dpo": [_clean(v) for v in bundle.ccc.dpo],
            "ccc": [_clean(v) for v in bundle.ccc.ccc],
            "deteriorating": bundle.ccc.deteriorating,
        },
        "governance": [
            {"name": m.name, "value": m.value, "light": m.light, "note": m.note}
            for m in bundle.governance.metrics
        ],
        "value_driver": {
            "roic_series": [
                {"year": y, "roic": _clean(v)} for y, v in bundle.value_driver.roic_series
            ],
            "wacc": _clean(bundle.value_driver.wacc),
            "spread": _clean(bundle.value_driver.spread),
            "creates_value": bundle.value_driver.creates_value,
        } if bundle.value_driver else None,
    }

    elapsed = time.monotonic() - t0
    logger.info("Research for %s assembled in %.1f s", ticker_ns, elapsed)

    coc = bundle.cost_of_capital
    cost_of_capital_out = {
        "wacc":                _clean(coc.wacc),
        "risk_free_rate":      _clean(coc.risk_free_rate),
        "equity_risk_premium": _clean(coc.equity_risk_premium),
        "tax_rate":            _clean(coc.tax_rate),
        "equity_value":        _clean(coc.equity_value),
        "debt_value":          _clean(coc.debt_value),
        "debt_value_is_book":  coc.debt_value_is_book,
        "equity_weight":       _clean(coc.equity_weight),
        "debt_weight":         _clean(coc.debt_weight),
        "beta": {
            "raw_regression_beta":  _clean(coc.beta.raw_regression_beta),
            "raw_beta_obs":         coc.beta.raw_beta_obs,
            "raw_beta_source":      coc.beta.raw_beta_source,
            "blume_beta":           _clean(coc.beta.blume_beta),
            "bottom_up_beta":       _clean(coc.beta.bottom_up_beta),
            "avg_unlevered_beta":   _clean(coc.beta.avg_unlevered_beta),
            "unlevered_peer_betas": [_clean(b) for b in coc.beta.unlevered_peer_betas],
            "target_debt_to_equity": _clean(coc.beta.target_debt_to_equity),
            "peer_count":           coc.beta.peer_count,
            "beta_used":            _clean(coc.beta.beta_used),
            "beta_used_source":     coc.beta.beta_used_source,
        },
        "cost_of_equity": {
            "capm_ke":           _clean(coc.cost_of_equity.capm_ke),
            "capm_ke_bottom_up": _clean(coc.cost_of_equity.capm_ke_bottom_up),
            "beta_used":      _clean(coc.cost_of_equity.beta_used),
            "size_premium":   _clean(coc.cost_of_equity.size_premium),
            "implied_ke":         _clean(coc.cost_of_equity.implied_ke),
            "implied_method":     coc.cost_of_equity.implied_method,
            "implied_gap":        _clean(coc.cost_of_equity.implied_gap),
            "gordon_implied_ke":  _clean(coc.cost_of_equity.gordon_implied_ke),
            "rim_implied_ke":     _clean(coc.cost_of_equity.rim_implied_ke),
        },
        "cost_of_debt": {
            "kd_interest_based": _clean(coc.cost_of_debt.kd_interest_based),
            "kd_synthetic":      _clean(coc.cost_of_debt.kd_synthetic),
            "interest_coverage": _clean(coc.cost_of_debt.interest_coverage),
            "synthetic_spread":  _clean(coc.cost_of_debt.synthetic_spread),
            "kd_pretax_used":    _clean(coc.cost_of_debt.kd_pretax_used),
            "kd_aftertax_used":  _clean(coc.cost_of_debt.kd_aftertax_used),
            "method_used":       coc.cost_of_debt.method_used,
        },
        "warnings": coc.warnings,
    }

    return {
        "company":    company,
        "conviction": conviction_out,
        "quality":    quality_out,
        "cost_of_capital": cost_of_capital_out,
        "price":      price_section,
        "financials": {
            "income_statement": income_records,
            "balance_sheet":    balance_records,
            "cash_flow":        cashflow_records,
        },
        "ratios":     ratios_out,
        "valuation": {
            "model_used":           val_result.model_used,
            "route_reason":         val_result.route_reason,
            "confidence":           val_result.confidence,
            "intrinsic_value":      _clean(val_result.intrinsic_value),
            "market_divergence_pct": _clean(val_result.market_divergence_pct),
            "diverges_materially":  val_result.diverges_materially,
            "dcf":                  dcf_out,
            "residual_income":      ri_out,
            "excess_return":        er_out,
            "financial":            financial_out,
            "sotp":                 sotp_out,
            "path_to_breakeven":    breakeven_out,
            "relative":             relative_out,
            "comps":                comps_out,
            "india":                india_out,
            "broker_target_price":  _clean(val_result.broker_target_price),
            "broker_recommendation": val_result.broker_recommendation,
            "broker_analyst_count": val_result.broker_analyst_count,
            "broker_upside_pct":    _clean(val_result.broker_upside_pct),
            "model_vs_broker_pct":  _clean(val_result.model_vs_broker_pct),
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["meta"])
@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness + capacity check: universe size and cache population."""
    return {
        "status": "ok",
        "universe_size": len(_universe),
        "cache_entries": file_cache.cache_entry_count(),
    }


@app.get("/api/universe", tags=["meta"])
async def universe() -> list[dict]:
    """Full Nifty 500 universe with valuation families and data status.

    data_status: 'complete' when financials are cached, 'partial' when only
    the profile is cached, 'unknown' before first fetch.
    """
    reports_by_ticker = {e["ticker"] for e in _load_report_index()}
    out: list[dict] = []
    for base, entry in _universe.items():
        yf_t = entry.get("yfinance_ticker", f"{base}.NS")
        has_fin = file_cache.get(f"{yf_t}_financials", "financials") is not None
        has_prof = file_cache.get(f"{yf_t}_profile", "profile") is not None
        status = "complete" if has_fin else ("partial" if has_prof else "unknown")
        out.append({
            "ticker": base,
            "name": entry.get("name"),
            "sector": entry.get("sector"),
            "industry": entry.get("industry"),
            "valuation_family": entry.get("valuation_family"),
            "primary_model": entry.get("primary_model"),
            "data_status": status,
            "has_report": base in reports_by_ticker,
        })
    return out


def _load_report_index() -> list[dict]:
    index_path = _REPORT_DIR / "_index.json"
    try:
        return json.loads(index_path.read_text()) if index_path.exists() else []
    except (json.JSONDecodeError, OSError):
        return []


@app.get("/api/reports", tags=["report"])
async def list_reports() -> list[dict]:
    """Archive of generated reports (most recent first)."""
    return _load_report_index()


@app.get("/api/reports/file/{filename}", tags=["report"])
async def download_report(filename: str) -> FileResponse:
    """Re-download an archived report PDF by filename."""
    safe = Path(filename).name   # strip any path components
    path = _REPORT_DIR / safe
    if not path.exists() or path.suffix not in (".pdf", ".html"):
        raise HTTPException(status_code=404, detail=f"Report '{safe}' not found in archive.")
    media = "application/pdf" if path.suffix == ".pdf" else "text/html"
    return FileResponse(path=str(path), media_type=media, filename=safe)


_indices_cache: TTLCache = TTLCache(maxsize=4, ttl=60)


@app.get("/api/indices", tags=["meta"])
def indices() -> list[dict]:
    """Nifty index levels for the frontend ticker tape (60 s cache)."""
    cached = _indices_cache.get("tape")
    if cached is not None:
        return cached
    out: list[dict] = []
    for symbol, label in (("^NSEI", "NIFTY 50"), ("^CRSLDX", "NIFTY 500")):
        try:
            hist = _provider.get_prices(symbol, period="5d")
            closes = hist["Close"].dropna() if not hist.empty else None
            if closes is not None and len(closes) >= 2:
                last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                out.append({
                    "symbol": symbol, "label": label,
                    "level": round(last, 2),
                    "change": round(last - prev, 2),
                    "change_pct": round((last - prev) / prev * 100, 2) if prev else None,
                })
        except Exception:  # noqa: BLE001
            logger.warning("Index fetch failed for %s", symbol)
    _indices_cache["tape"] = out
    return out


@app.get("/api/tickers", tags=["meta"])
async def list_tickers() -> list[dict]:
    """Return the curated list of supported tickers (147-ticker Nifty 500 subset)."""
    return [
        {
            "ticker": row["ticker"],
            "name":   row["company_name"],
            "sector": row["sector"],
        }
        for _, row in _nifty500_df.iterrows()
    ]

@app.get("/api/backtest", tags=["research"])
def backtest(force_refresh: bool = False) -> dict:
    """Return the backtest results for the India valuation factors."""
    if not force_refresh and "result" in _backtest_cache:
        logger.info("Cache hit for backtest")
        return _backtest_cache["result"]
        
    try:
        logger.info("Running backtest (force_refresh=%s)...", force_refresh)
        res = run_backtest(force_refresh)
        out = dataclasses.asdict(res)
        _backtest_cache["result"] = out
        return out
    except Exception as exc:
        logger.error("Backtest failed:\n%s", traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Backtest failed: {exc}",
        ) from exc


@app.get("/api/prices/{ticker}", tags=["research"])
async def get_prices(ticker: str, period: str = "1y") -> list[dict]:
    """Return OHLCV price history for TradingView Lightweight Charts.

    Each record has ``time`` (YYYY-MM-DD) plus open/high/low/close/volume.
    Returns the last ``period`` of trading days (default 1y).
    """
    ticker_ns = _normalize_ticker(ticker)
    df = _provider.get_prices(ticker_ns, period=period)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No price data available for '{ticker_ns}'.",
        )
    records: list[dict] = []
    for date, row in df.iterrows():
        records.append({
            "time":   date.strftime("%Y-%m-%d"),
            "open":   _clean(row.get("Open")),
            "high":   _clean(row.get("High")),
            "low":    _clean(row.get("Low")),
            "close":  _clean(row.get("Close")),
            "volume": int(row.get("Volume") or 0),
        })
    return records


@app.get("/api/research/{ticker}", tags=["research"])
@limiter.limit("10/minute")
def research(ticker: str, request: Request) -> dict:
    """Return the full structured research dict for a Nifty 500 ticker.

    Accepts the ticker with or without the .NS suffix (e.g. ``RELIANCE`` or
    ``RELIANCE.NS``).  Results are cached for 30 minutes.
    """
    ticker_ns = _normalize_ticker(ticker)

    cached = _research_cache.get(ticker_ns)
    if cached is not None:
        logger.info("Cache hit for %s", ticker_ns)
        return cached

    try:
        result = _build_research(ticker_ns)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Research failed for %s:\n%s", ticker_ns, traceback.format_exc()
        )
        # A single company failing must surface as a clean, structured error —
        # never an unhandled 500.  502 (upstream data failure) distinguishes a
        # market-data problem from a bug in this service.
        raise HTTPException(
            status_code=502,
            detail={
                "error": "analysis_failed",
                "ticker": ticker_ns,
                "message": str(exc),
            },
        ) from exc

    _research_cache[ticker_ns] = result
    return result


@app.get("/api/report/{ticker}/pdf", tags=["report"])
@limiter.limit("10/minute")
def report_pdf(
    ticker: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    """Generate and return a PDF equity research report for a Nifty 500 ticker.

    The report is built on the fly from real yfinance data.  Generation takes
    15–40 seconds on first call; subsequent calls within the 30-minute cache
    window skip the data-fetch step (WeasyPrint still renders the PDF).
    The generated file is deleted from disk after the response is sent.
    """
    ticker_ns = _normalize_ticker(ticker)

    # Ensure data is fetched (warm cache if needed) before the PDF render
    if _research_cache.get(ticker_ns) is None:
        try:
            result = _build_research(ticker_ns)
            _research_cache[ticker_ns] = result
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Pre-fetch failed for %s:\n%s", ticker_ns, traceback.format_exc()
            )
            raise HTTPException(
                status_code=500,
                detail=f"Data fetch failed for '{ticker_ns}': {exc}",
            ) from exc

    # Generate the PDF (or HTML fallback if WeasyPrint system libs are missing)
    try:
        report_path: Path = generate_report(ticker_ns, _provider, _config)
    except Exception as exc:
        logger.error(
            "PDF generation failed for %s:\n%s", ticker_ns, traceback.format_exc()
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"PDF generation failed for '{ticker_ns}': {exc}. "
                "Ensure WeasyPrint system dependencies (pango, cairo) are installed."
            ),
        ) from exc

    if report_path.suffix == ".html":
        # WeasyPrint fell back to HTML — surface a clear 503 rather than sending HTML
        background_tasks.add_task(report_path.unlink, True)
        raise HTTPException(
            status_code=503,
            detail=(
                "PDF rendering unavailable — WeasyPrint system libraries are missing. "
                "Install: libpango-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libffi-dev "
                "(on Railway these are added via nixpacks.toml)."
            ),
        )

    base = ticker_ns.replace(".NS", "")
    # PDFs are kept on disk and indexed in _index.json for the /reports archive.
    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=f"{base}_equity_research.pdf",
    )


@app.get("/api/report/{ticker}/stream", tags=["report"])
def report_stream(ticker: str, request: Request):
    """Server-Sent Events stream of report-generation progress.

    Emits ``progress`` events for each pipeline step, then a ``done`` event
    carrying the download URL (or an ``error`` event). The heavy work runs in
    a worker thread; events are forwarded as they arrive so the frontend can
    render a live step tracker.
    """
    from queue import Queue, Empty
    from starlette.responses import StreamingResponse

    ticker_ns = _normalize_ticker(ticker)
    q: Queue = Queue()

    def worker() -> None:
        try:
            path = generate_report(
                ticker_ns, _provider, _config,
                on_progress=lambda step: q.put(("progress", step)),
            )
            if path.suffix == ".pdf":
                q.put(("done", f"/api/reports/file/{path.name}"))
            else:
                q.put(("error", "PDF rendering unavailable — WeasyPrint system libraries missing."))
        except Exception as exc:  # noqa: BLE001
            logger.error("Streamed report failed for %s:\n%s", ticker_ns, traceback.format_exc())
            q.put(("error", str(exc)))

    Thread(target=worker, daemon=True).start()

    def event_source():
        while True:
            try:
                kind, payload = q.get(timeout=180)
            except Empty:
                yield 'event: error\ndata: {"message": "Generation timed out."}\n\n'
                return
            if kind == "progress":
                yield f'event: progress\ndata: {json.dumps({"step": payload})}\n\n'
            elif kind == "done":
                yield f'event: done\ndata: {json.dumps({"url": payload})}\n\n'
                return
            else:
                yield f'event: error\ndata: {json.dumps({"message": payload})}\n\n'
                return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
