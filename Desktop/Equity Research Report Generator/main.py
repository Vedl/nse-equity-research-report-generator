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

from equity_research.analysis.comps import compute_comps
from equity_research.analysis.dcf import run_dcf
from equity_research.analysis.ratios import compute_ratios
from equity_research.config import load_config
from equity_research.data.yfinance_provider import YFinanceProvider
from equity_research.report.builder import generate_report

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

# ---------------------------------------------------------------------------
# Rate limiter + cache
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

# TTL = 1 800 s (30 min).  Yahoo data freshness is good enough at this cadence.
_research_cache: TTLCache = TTLCache(maxsize=128, ttl=1800)

# ---------------------------------------------------------------------------
# Startup pre-warm
# ---------------------------------------------------------------------------

_PREWARM_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "BAJFINANCE", "MARUTI", "WIPRO", "ASIANPAINT",
]


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


def _dcf_divergence(intrinsic: float, current_price: float | None) -> dict:
    """Return market_divergence_pct and diverges_materially for a DCF result.

    diverges_materially = True when |intrinsic − price| / price > 35%.
    This signals that the FCFF model may be sensitive to capex assumptions —
    typical for capital-intensive or high-growth companies.  It is not a claim
    that the model is wrong; it is a transparency flag for frontend presentation.
    """
    if current_price is None or current_price <= 0:
        return {"market_divergence_pct": None, "diverges_materially": False}
    div_pct = (intrinsic - current_price) / current_price
    return {
        "market_divergence_pct": _clean(div_pct),
        "diverges_materially": abs(div_pct) > 0.35,
    }


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

    dcf_result = None
    try:
        dcf_result = run_dcf(profile, financials, _config)
    except (ValueError, ZeroDivisionError) as exc:
        logger.warning("DCF skipped for %s: %s", ticker_ns, exc)

    comps_result = None
    try:
        comps_result = compute_comps(profile, financials, _provider, _config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Comps skipped for %s: %s", ticker_ns, exc)

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

    # DCF section
    dcf_out: dict | None = None
    if dcf_result is not None:
        sensitivity_rows: list[list[float | None]] = [
            [_clean(v) for v in row]
            for _, row in dcf_result.sensitivity.iterrows()
        ]
        # Axis labels pulled directly from the DataFrame so they always match the
        # table values.  Index = WACC (rows), columns = terminal growth.
        # Labels are stored as "7.49%" strings in the DataFrame — parse to floats.
        def _pct_str_to_float(s: str) -> float:
            return round(float(s.rstrip("%")) / 100, 4)

        dcf_out = {
            "intrinsic_value": _clean(dcf_result.intrinsic_value_per_share),
            "sensitivity":     sensitivity_rows,
            "sensitivity_wacc_labels": [
                _pct_str_to_float(s)
                for s in dcf_result.sensitivity.index.tolist()
            ],
            "sensitivity_tg_labels": [
                _pct_str_to_float(s)
                for s in dcf_result.sensitivity.columns.tolist()
            ],
            # Extra fields required for client-side DCF recalculation (DCF sliders)
            "base_fcff":          _clean(dcf_result.base_fcff),
            "growth_rate":        _clean(dcf_result.growth_rate),
            "net_debt":           _clean(dcf_result.net_debt),
            "shares_outstanding": _clean(dcf_result.shares_outstanding),
            "assumptions": {
                "wacc":            _clean(dcf_result.wacc),
                "terminal_growth": _clean(dcf_result.terminal_growth),
                "projection_years": _config.dcf.projection_horizon,
                "risk_free_rate":   _config.market.risk_free_rate,
                "erp":              _config.market.equity_risk_premium,
            },
            # Divergence fields — flag when DCF deviates materially from market price.
            # diverges_materially = True does NOT mean the model is wrong; FCFF DCF
            # is known to understate capital-intensive or high-growth companies
            # whose future cash generation exceeds the trailing period captured here.
            **_dcf_divergence(
                dcf_result.intrinsic_value_per_share,
                _clean(profile.get("current_price")),
            ),
        }

    # Comps section
    comps_out: list[dict] = []
    if comps_result is not None:
        for pm in comps_result.peers:
            upper = pm.ticker.upper()
            comps_out.append({
                "ticker":    pm.ticker,
                "name":      _TICKER_NAME.get(upper, pm.ticker),
                "pe":        _clean(pm.pe),
                "ev_ebitda": _clean(pm.ev_ebitda),
                "pb":        _clean(pm.pb),
                "ev_sales":  _clean(pm.ev_sales),
            })

    elapsed = time.monotonic() - t0
    logger.info("Research for %s assembled in %.1f s", ticker_ns, elapsed)

    return {
        "company":    company,
        "price":      price_section,
        "financials": {
            "income_statement": income_records,
            "balance_sheet":    balance_records,
            "cash_flow":        cashflow_records,
        },
        "ratios":     ratios_out,
        "valuation": {
            "dcf":   dcf_out,
            "comps": comps_out,
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    """Liveness check — always returns 200 if the process is up."""
    return {"status": "ok"}


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
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed for '{ticker_ns}': {exc}",
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
    background_tasks.add_task(report_path.unlink, True)  # delete after send
    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=f"{base}_equity_research.pdf",
    )
