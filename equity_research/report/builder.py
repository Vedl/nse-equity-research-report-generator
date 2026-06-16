"""PDF report builder — institutional 7-page layout fed by the research pipeline.

Entry point: ``generate_report(ticker, provider, config) -> Path``

WeasyPrint runs in a child subprocess so DYLD_LIBRARY_PATH (Homebrew pango on
macOS) is set before the dynamic linker resolves shared libraries. On library
failure the HTML is written instead and the caller surfaces a clear error.

A JSON index of generated reports is maintained at ``<output_dir>/_index.json``
so the frontend can present an archive.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from equity_research.analysis.pipeline import ResearchBundle, run_research_pipeline
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider
from equity_research.data.yfinance_provider import _normalize_ticker
from equity_research.report import charts
from equity_research.utils.formatting import NA, fmt_pct, fmt_x, format_inr, indian_group, safe_divide

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# WeasyPrint subprocess writer
# ---------------------------------------------------------------------------


def _make_env_with_brew_libs() -> dict[str, str]:
    env = os.environ.copy()
    try:
        result = subprocess.run(["brew", "--prefix"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            brew_lib = f"{result.stdout.strip()}/lib"
            existing = env.get("DYLD_LIBRARY_PATH", "")
            env["DYLD_LIBRARY_PATH"] = f"{brew_lib}:{existing}" if existing else brew_lib
    except Exception:  # noqa: BLE001
        pass
    return env


def _write_pdf(html: str, pdf_path: Path) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html)
        tmp_html = fh.name
    script = (
        f"from weasyprint import HTML; "
        f"HTML(filename={repr(tmp_html)}).write_pdf({repr(str(pdf_path))})"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=_make_env_with_brew_libs(), capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
    finally:
        os.unlink(tmp_html)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _is_nan(v: Any) -> bool:
    return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def _cr(v: Any, decimals: int = 0) -> str:
    """Raw INR → Indian-grouped Crores string (no ₹ sign, for dense tables)."""
    if _is_nan(v):
        return NA
    return indian_group(float(v) / 1e7, decimals)


def _rs(v: Any, decimals: int = 0) -> str:
    if _is_nan(v):
        return NA
    return format_inr(float(v), unit="rupee", decimals=decimals)


def _pct(v: Any, decimals: int = 1) -> str:
    if _is_nan(v):
        return NA
    return f"{float(v)*100:.{decimals}f}%"


def _signed_pct(v: Any) -> str:
    if _is_nan(v):
        return NA
    return f"{float(v)*100:+.1f}%"


def _x(v: Any, decimals: int = 1) -> str:
    if _is_nan(v):
        return NA
    return f"{float(v):.{decimals}f}×"


def _fy_label(year: int, estimate: bool = False) -> str:
    return f"FY{int(year) % 100:02d}" + ("E" if estimate else "")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _mcap_band(market_cap: float | None) -> str:
    if not market_cap:
        return "Mkt cap n/a"
    if market_cap >= 50_000e7:
        return f"Large Cap · {format_inr(market_cap)}"
    if market_cap >= 17_000e7:
        return f"Mid Cap · {format_inr(market_cap)}"
    return f"Small Cap · {format_inr(market_cap)}"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_stats(profile: dict, bundle: ResearchBundle) -> list[dict]:
    dy = profile.get("dividend_yield")
    return [
        {"label": "Market cap", "value": format_inr(profile.get("market_cap"))},
        {"label": "P/E (TTM)", "value": fmt_x(profile.get("trailing_pe"))},
        {"label": "P/E (Fwd)", "value": fmt_x(profile.get("forward_pe"))},
        {"label": "EV/EBITDA (TTM)", "value": fmt_x(profile.get("enterprise_to_ebitda"))},
        {"label": "P/B", "value": fmt_x(profile.get("price_to_book"))},
        {"label": "Dividend yield", "value": fmt_pct(dy) if dy is not None else NA},
        {"label": "52-week high", "value": _rs(profile.get("fifty_two_week_high"), 0)},
        {"label": "52-week low", "value": _rs(profile.get("fifty_two_week_low"), 0)},
        {"label": "Beta (5Y monthly)", "value": f"{bundle.beta.beta:.2f} ({bundle.beta.source.replace('_',' ')})"},
        {"label": "Promoter holding", "value": next(
            (m.value for m in bundle.governance.metrics if m.name == "Promoter holding"), NA)},
        {"label": "Piotroski F-Score", "value": f"{bundle.piotroski.score}/9"},
        {"label": "Confidence score", "value": f"{bundle.conviction.confidence_score}/100"},
    ]


_MODEL_LABELS = {
    "fcff": "FCFF multi-stage DCF",
    "financial": "Justified P/B + H-Model DDM",
    "ri": "Residual Income (Penman)",
    "sotp": "Sum-of-the-Parts",
    "ev_sales": "EV/Sales relative",
    "ev_ebitda": "EV/EBITDA relative",
    "excess_return": "Excess return (bank)",
}


def _build_thesis(profile: dict, bundle: ResearchBundle) -> dict:
    """Rule-based, opinionated thesis: rating call + the strongest evidence."""
    c = bundle.conviction
    name = profile.get("long_name") or profile.get("ticker", "The company")
    sector = profile.get("sector") or "its sector"

    verdict = {
        "BUY": "trades meaningfully below our blended intrinsic value",
        "SELL": "trades meaningfully above our blended intrinsic value",
        "HOLD": "trades close to our blended intrinsic value",
        "NR": "could not be assigned a rating on available data",
    }[c.rating]
    lead = (
        f"{name} {verdict}"
        + (f" of {_rs(c.target_price, 0)} ({_signed_pct(c.upside_pct)} vs CMP)" if c.target_price else "")
        + f", derived from a {_MODEL_LABELS.get(c.primary_model, c.primary_model)} primary model"
        + (f" cross-checked against {c.secondary_model.lower()}" if c.secondary_model else "")
        + f". Fundamental quality screens score {bundle.piotroski.score}/9 on Piotroski and "
        + f"{bundle.caq.score}/{bundle.caq.max_score} on capital allocation."
    )

    bullets: list[str] = []
    vd = bundle.value_driver
    if vd and vd.spread is not None:
        if vd.creates_value:
            bullets.append(
                f"Value creator: ROIC of {_pct(vd.latest_roic)} exceeds WACC of {_pct(vd.wacc)} "
                f"(spread {_signed_pct(vd.spread)}) — justifies a premium to invested capital.")
        else:
            bullets.append(
                f"Value at risk: ROIC of {_pct(vd.latest_roic)} trails WACC of {_pct(vd.wacc)} — "
                "the business currently destroys economic value at the margin.")
    if bundle.accruals.cfo_ebitda is not None:
        if bundle.accruals.cfo_ebitda >= 0.65:
            bullets.append(
                f"Earnings are cash-backed: CFO/EBITDA of {bundle.accruals.cfo_ebitda:.2f} clears "
                "the 0.65 quality threshold.")
        else:
            bullets.append(
                f"Earnings quality watch: CFO/EBITDA of {bundle.accruals.cfo_ebitda:.2f} is below "
                "the 0.65 threshold (Sloan 1996).")
    if bundle.beneish.flagged:
        bullets.append("Forensic flag: Beneish M-Score above −1.78 — treat reported earnings with caution.")
    if c.models_agree is True:
        bullets.append("Primary and secondary models agree within 15% — high conviction in the value range.")
    elif c.models_agree is False:
        bullets.append("Primary and secondary models diverge by more than 15% — wider error bars on the target.")
    india = bundle.valuation.india_result
    if india and india.is_psu:
        bullets.append("PSU governance discount applied — state ownership historically suppresses capital-allocation quality.")
    if not bullets:
        bullets.append(f"{sector} positioning and valuation summarised in the pages that follow.")
    return {"lead": lead, "bullets": bullets[:5]}


def _build_summary_bullets(profile: dict, bundle: ResearchBundle) -> list[str]:
    c = bundle.conviction
    out: list[str] = []
    out.append(
        f"12-month target {_rs(c.target_price, 0)} = 60% × {_MODEL_LABELS.get(c.primary_model, c.primary_model)} "
        + (f"+ 40% × {c.secondary_model}" if c.secondary_model else "(single model — no secondary available)") + ".")
    if c.bear_value and c.bull_value:
        out.append(f"Scenario band: bear {_rs(c.bear_value, 0)} / base {_rs(c.target_price, 0)} / bull {_rs(c.bull_value, 0)}.")
    if bundle.valuation.broker_target_price:
        out.append(
            f"Street consensus target {_rs(bundle.valuation.broker_target_price, 0)} "
            f"({bundle.valuation.broker_analyst_count or '?'} analysts, "
            f"{(bundle.valuation.broker_recommendation or 'n/a').upper()}) — our model is "
            f"{_signed_pct(bundle.valuation.model_vs_broker_pct)} vs consensus.")
    if bundle.altman.applicable and bundle.altman.zone != "N/A":
        out.append(f"Balance-sheet health: Altman Z″ of {bundle.altman.z_score:.2f} — {bundle.altman.zone} zone.")
    dup = [y for y in bundle.dupont.years if y.roe is not None]
    if dup:
        out.append(f"ROE of {_pct(dup[-1].roe)} decomposed on page 4 (DuPont 5-factor).")
    return out[:5]


def _financial_summary_table(
    financials: dict[str, pd.DataFrame],
    bundle: ResearchBundle,
    profile: dict,
    config: AppConfig,
) -> dict:
    """5-year history + 2-year forward estimates (marked E) per the page-3 spec."""
    income = financials["income"]
    balance = financials["balance_sheet"]
    cashflow = financials["cash_flow"]

    hist_years = [int(y) for y in income.index.tolist()][-5:]
    if not hist_years:
        return {"years": [], "rows": []}

    g = None
    if bundle.valuation.dcf_result:
        g = bundle.valuation.dcf_result.growth_rate
    if g is None:
        g = 0.08
    fwd_years = [hist_years[-1] + 1, hist_years[-1] + 2]
    years_lbl = [_fy_label(y) for y in hist_years] + [_fy_label(y, estimate=True) for y in fwd_years]

    def col(df: pd.DataFrame, name: str) -> dict[int, float]:
        if name not in df.columns:
            return {}
        return {int(y): v for y, v in df[name].dropna().items()}

    rev = col(income, "total_revenue")
    ebitda = col(income, "ebitda")
    ebit = col(income, "operating_income")
    pat = col(income, "net_income")
    eps = col(income, "diluted_eps") or col(income, "basic_eps")
    cfo = col(cashflow, "operating_cash_flow")
    capex = col(cashflow, "capital_expenditure")
    fcf = col(cashflow, "free_cash_flow")
    debt = col(balance, "total_debt")
    cash = col(balance, "cash_and_equivalents")
    eq = col(balance, "stockholders_equity")
    div = col(cashflow, "dividends_paid")
    shares = profile.get("shares_outstanding")
    roic_map = dict(bundle.value_driver.roic_series) if bundle.value_driver else {}

    # Forward estimates: revenue grows at g; margins held at latest-year levels.
    last = hist_years[-1]
    est: dict[str, dict[int, float]] = {"rev": {}, "ebitda": {}, "ebit": {}, "pat": {}, "eps": {}}
    if last in rev:
        m_ebitda = safe_divide(ebitda.get(last), rev.get(last))
        m_ebit = safe_divide(ebit.get(last), rev.get(last))
        m_pat = safe_divide(pat.get(last), rev.get(last))
        r = rev[last]
        for i, fy in enumerate(fwd_years, start=1):
            r_f = r * (1 + g) ** i
            est["rev"][fy] = r_f
            if m_ebitda is not None:
                est["ebitda"][fy] = r_f * m_ebitda
            if m_ebit is not None:
                est["ebit"][fy] = r_f * m_ebit
            if m_pat is not None:
                est["pat"][fy] = r_f * m_pat
                if shares:
                    est["eps"][fy] = r_f * m_pat / shares

    all_years = hist_years + fwd_years

    def row(label: str, getter, fmt, cls: str = "") -> dict:
        vals = []
        for y in all_years:
            v = getter(y)
            vals.append(fmt(v) if v is not None else NA)
        return {"label": label, "vals": vals, "cls": cls}

    def merged(hist: dict, estd: dict):
        return lambda y: hist.get(y, estd.get(y))

    def yoy(y: int) -> float | None:
        r = merged(rev, est["rev"])
        cur, prev = r(y), r(y - 1)
        return safe_divide(cur - prev, prev) if cur is not None and prev is not None else None

    def nde(y: int) -> float | None:
        if y in debt and y in ebitda and ebitda[y]:
            return (debt[y] - cash.get(y, 0.0)) / ebitda[y]
        return None

    def roe_f(y: int) -> float | None:
        return safe_divide(pat.get(y), eq.get(y))

    def dps_f(y: int) -> float | None:
        if y in div and shares:
            return abs(div[y]) / shares
        return None

    rows = [
        row("Revenue", merged(rev, est["rev"]), _cr),
        row("  YoY growth", yoy, _signed_pct, cls="mrow"),
        row("EBITDA", merged(ebitda, est["ebitda"]), _cr),
        row("  EBITDA margin", lambda y: safe_divide(merged(ebitda, est['ebitda'])(y), merged(rev, est['rev'])(y)), _pct, cls="mrow"),
        row("EBIT", merged(ebit, est["ebit"]), _cr),
        row("PAT", merged(pat, est["pat"]), _cr),
        row("Diluted EPS (₹)", merged(eps, est["eps"]), lambda v: f"{v:,.2f}"),
        row("DPS (₹)", dps_f, lambda v: f"{v:,.2f}"),
        row("CFO", lambda y: cfo.get(y), _cr),
        row("CapEx", lambda y: capex.get(y), _cr),
        row("FCFF", lambda y: fcf.get(y), _cr),
        row("Net debt / EBITDA", nde, _x),
        row("RoE", roe_f, _pct),
        row("RoIC", lambda y: roic_map.get(y), _pct),
    ]
    return {"years": years_lbl, "rows": rows}


def _dupont_table(bundle: ResearchBundle) -> dict:
    ys = bundle.dupont.years[-5:]
    years = [_fy_label(y.year) for y in ys]
    rows = [
        {"label": "Tax burden (NI/EBT)", "vals": [_x(y.tax_burden, 2) for y in ys]},
        {"label": "Interest burden (EBT/EBIT)", "vals": [_x(y.interest_burden, 2) for y in ys]},
        {"label": "EBIT margin", "vals": [_pct(y.ebit_margin) for y in ys]},
        {"label": "Asset turnover", "vals": [_x(y.asset_turnover, 2) for y in ys]},
        {"label": "Financial leverage (TA/E)", "vals": [_x(y.leverage, 2) for y in ys]},
        {"label": "ROE", "vals": [_pct(y.roe) for y in ys]},
    ]
    return {"years": years, "rows": rows, "annotations": bundle.dupont.annotations[-3:]}


def _sensitivity_html(df: pd.DataFrame) -> str:
    """Heat-mapped sensitivity table; the base case (centre cell) is navy."""
    if df is None or df.empty:
        return ""
    mid_r, mid_c = len(df) // 2, len(df.columns) // 2
    try:
        center = float(df.iloc[mid_r, mid_c])
    except Exception:  # noqa: BLE001
        center = None

    def cell_class(v: float, r: int, c: int) -> str:
        if r == mid_r and c == mid_c:
            return "s-base"
        if center is None or center == 0:
            return "s-mid"
        pct = (v - center) / abs(center)
        if pct >= 0.20:
            return "s-vhi"
        if pct >= 0.05:
            return "s-hi"
        if pct >= -0.05:
            return "s-mid"
        if pct >= -0.20:
            return "s-lo"
        return "s-vlo"

    header = "<tr><th>WACC \\ g</th>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr>"
    body = []
    for r, (idx_label, row) in enumerate(df.iterrows()):
        cells = f"<th>{idx_label}</th>"
        for c, v in enumerate(row):
            if _is_nan(v):
                cells += '<td class="s-na">n/a</td>'
            else:
                cells += f'<td class="{cell_class(float(v), r, c)}">₹{indian_group(float(v))}</td>'
        body.append(f"<tr>{cells}</tr>")
    return ('<table class="sens-table"><thead>' + header + "</thead><tbody>"
            + "\n".join(body) + "</tbody></table>")


def _comps_section(bundle: ResearchBundle, profile: dict, ticker_names: dict[str, str]) -> dict:
    cr = bundle.valuation.comps_result
    rel = bundle.valuation.relative
    price = profile.get("current_price")
    rows = []
    if cr:
        for pm in cr.peers:
            rows.append({
                "name": ticker_names.get(pm.ticker.upper(), pm.ticker.replace(".NS", "")),
                "pe": _x(pm.pe), "ev_ebitda": _x(pm.ev_ebitda),
                "pb": _x(pm.pb), "ev_sales": _x(pm.ev_sales),
                "is_subject": False,
            })
        rows.append({
            "name": profile.get("long_name") or profile.get("ticker", ""),
            "pe": _x(profile.get("trailing_pe")),
            "ev_ebitda": _x(profile.get("enterprise_to_ebitda")),
            "pb": _x(profile.get("price_to_book")),
            "ev_sales": _x(profile.get("enterprise_to_revenue")),
            "is_subject": True,
        })

    premium_note = ""
    if cr and cr.median_pe and profile.get("trailing_pe"):
        prem = profile["trailing_pe"] / cr.median_pe - 1.0
        name = profile.get("long_name") or "The company"
        premium_note = (
            f"{name} trades at a {abs(prem)*100:.0f}% "
            f"{'premium' if prem >= 0 else 'discount'} to the sector median on P/E (TTM)."
        )
        if prem > 0.30:
            premium_note += " A >30% premium requires growth/quality justification — treated as a risk factor."

    implied = []
    if rel:
        for label, v in (("P/E basis", rel.implied_pe), ("EV/EBITDA basis", rel.implied_ev_ebitda),
                         ("P/B basis", rel.implied_pb), ("Peer median (blended)", rel.median)):
            if v is not None:
                up = safe_divide(v - price, price) if price else None
                implied.append({"label": label, "value": _rs(v, 0),
                                "upside": _signed_pct(up),
                                "css": "up" if (up or 0) >= 0 else "down"})

    median = {
        "pe": _x(cr.median_pe) if cr else NA,
        "ev_ebitda": _x(cr.median_ev_ebitda) if cr else NA,
        "pb": _x(cr.median_pb) if cr else NA,
        "ev_sales": _x(cr.median_ev_sales) if cr else NA,
    }
    return {"rows": rows, "median": median, "premium_note": premium_note, "implied": implied}


def _risk_factors(profile: dict, bundle: ResearchBundle) -> list[str]:
    risks: list[str] = []
    if bundle.beneish.flagged:
        risks.append("Beneish M-Score above the −1.78 manipulation threshold — reported earnings may overstate economic earnings; audit-quality diligence warranted.")
    for f in bundle.accruals.flags:
        risks.append(f + ".")
    if bundle.ccc.deteriorating:
        risks.append("Working-capital cycle has lengthened for three consecutive years — rising cash absorption could pressure free cash flow.")
    if bundle.altman.applicable and bundle.altman.zone == "Distress":
        risks.append(f"Altman Z″-Score of {bundle.altman.z_score:.2f} sits in the distress zone — refinancing and covenant risk are material.")
    elif bundle.altman.applicable and bundle.altman.zone == "Grey":
        risks.append(f"Altman Z″-Score of {bundle.altman.z_score:.2f} is in the grey zone — balance-sheet headroom is limited in a downturn.")
    india = bundle.valuation.india_result
    if india and india.is_psu:
        risks.append("State ownership: government policy objectives can override minority-shareholder economics (pricing, dividends, capex direction).")
    vd = bundle.value_driver
    if vd and vd.creates_value is False:
        risks.append("ROIC below WACC: continued growth at sub-WACC returns destroys value rather than creating it.")
    cr = bundle.valuation.comps_result
    if cr and cr.median_pe and profile.get("trailing_pe") and profile["trailing_pe"] / cr.median_pe - 1 > 0.30:
        risks.append("Valuation premium of more than 30% to the peer median on P/E — multiple compression is a key de-rating risk.")
    if bundle.conviction.models_agree is False:
        risks.append("Primary and secondary valuation models diverge by more than 15% — model risk on the price target is elevated.")
    if bundle.beta.source != "regression":
        risks.append(f"Beta estimated via {bundle.beta.source.replace('_', ' ')} rather than a full 60-month regression — discount-rate uncertainty is higher than usual.")
    if len(risks) < 4:
        risks.append("Macro: earnings and the discount rate are sensitive to India rate cycles, INR moves, and commodity input costs.")
    if len(risks) < 4:
        risks.append("Data: statements sourced from Yahoo Finance may lag exchange filings; material restatements would change model outputs.")
    return risks[:6]


def _earnings_quality_section(bundle: ResearchBundle) -> dict:
    """Format the financial-reliability overlay for the report (risk overlay)."""
    eq = bundle.earnings_quality
    verdict_css = {"Green": "green", "Amber": "amber", "Red": "red", "Unrated": "na"}.get(
        eq.verdict, "na"
    )
    acc_pct = (
        f"{eq.accrual_sector_percentile:.0f}th"
        if eq.accrual_sector_percentile is not None else None
    )
    f_pct = (
        f"{eq.fscore_sector_percentile:.0f}th"
        if eq.fscore_sector_percentile is not None else None
    )
    return {
        "verdict": eq.verdict,
        "verdict_css": verdict_css,
        "verdict_reason": eq.verdict_reason,
        "score": f"{eq.quality_score:.0f}" if eq.quality_score is not None else NA,
        "components": [
            {"name": c.name, "flag": c.flag, "reason": c.reason} for c in eq.components
        ],
        "accrual_percentile": acc_pct,
        "fscore_percentile": f_pct,
        "sector": eq.sector or "sector",
        "peer_n": eq.peer_sample_size,
        "bs_accrual": _pct(eq.accruals.bs_accrual_ratio) if eq.accruals.bs_accrual_ratio is not None else NA,
        "cf_accrual": _pct(eq.accruals.cf_accrual_ratio) if eq.accruals.cf_accrual_ratio is not None else NA,
    }


def _appendix_tables(financials: dict[str, pd.DataFrame]) -> dict:
    def table(df: pd.DataFrame, defs: list[tuple[str, str]]) -> dict:
        years = [int(y) for y in df.index.tolist()][-5:]
        rows = []
        for label, colname in defs:
            vals = []
            for y in years:
                v = df.loc[y, colname] if colname in df.columns and y in df.index else None
                vals.append(_cr(v))
            rows.append({"label": label, "vals": vals})
        return {"years": [_fy_label(y) for y in years], "rows": rows}

    income_defs = [
        ("Revenue", "total_revenue"), ("Cost of revenue", "cost_of_revenue"),
        ("Gross profit", "gross_profit"), ("SG&A", "selling_general_admin"),
        ("EBITDA", "ebitda"), ("Depreciation", "depreciation_amortization"),
        ("EBIT", "operating_income"), ("Interest expense", "interest_expense"),
        ("Profit before tax", "pretax_income"), ("Tax", "tax_provision"),
        ("PAT", "net_income"),
    ]
    balance_defs = [
        ("Total assets", "total_assets"), ("Net PP&E", "net_ppe"),
        ("Current assets", "current_assets"), ("Cash & equivalents", "cash_and_equivalents"),
        ("Receivables", "accounts_receivable"), ("Inventory", "inventory"),
        ("Current liabilities", "current_liabilities"), ("Payables", "accounts_payable"),
        ("Total debt", "total_debt"), ("Long-term debt", "long_term_debt"),
        ("Total liabilities", "total_liabilities"), ("Retained earnings", "retained_earnings"),
        ("Shareholders' equity", "stockholders_equity"),
    ]
    cashflow_defs = [
        ("Cash from operations", "operating_cash_flow"),
        ("Capital expenditure", "capital_expenditure"),
        ("Free cash flow", "free_cash_flow"),
        ("Cash from investing", "investing_cash_flow"),
        ("Dividends paid", "dividends_paid"),
        ("Share repurchases", "share_repurchase"),
        ("Δ Working capital", "change_in_working_capital"),
    ]
    return {
        "income": table(financials["income"], income_defs),
        "balance": table(financials["balance_sheet"], balance_defs),
        "cashflow": table(financials["cash_flow"], cashflow_defs),
    }


def _assumptions(bundle: ResearchBundle, config: AppConfig) -> list[dict]:
    rows = [
        {"label": "Risk-free rate", "value": _pct(config.market.risk_free_rate, 2),
         "note": "India 10Y G-Sec yield (config / RISK_FREE_RATE env)"},
        {"label": "Equity risk premium", "value": _pct(config.market.equity_risk_premium, 2),
         "note": "Damodaran India ERP, updated annually (INDIA_ERP env)"},
        {"label": "Beta", "value": f"{bundle.beta.beta:.2f}", "note": bundle.beta.note},
        {"label": "Corporate tax rate", "value": _pct(config.market.tax_rate, 0),
         "note": "Applied to NOPAT and after-tax cost of debt"},
        {"label": "Terminal growth", "value": _pct(config.dcf.terminal_growth_rate, 1),
         "note": "≈ nominal India GDP growth × 0.7 (Gordon growth)"},
        {"label": "Explicit horizon", "value": f"{config.dcf.projection_horizon}+{config.dcf.stage2_fade_years} yrs",
         "note": "Stage 1 at g1, Stage 2 linear fade to terminal growth"},
    ]
    dcf = bundle.valuation.dcf_result
    if dcf:
        wc = dcf.wacc_components
        rows += [
            {"label": "Cost of equity (Ke)", "value": _pct(wc.cost_of_equity, 2),
             "note": f"CAPM + size premium {_pct(wc.size_premium, 1)} (CFA L2 Reading 21)"},
            {"label": "After-tax cost of debt", "value": _pct(wc.cost_of_debt_aftertax, 2),
             "note": "Interest expense / 3Y-avg debt, clamped 1–30%"},
            {"label": "WACC", "value": _pct(wc.wacc, 2),
             "note": f"E/V {_pct(wc.equity_weight, 0)}, D/V {_pct(wc.debt_weight, 0)} (3Y-avg debt)"},
            {"label": "Stage-1 FCFF growth", "value": _pct(dcf.growth_rate, 1),
             "note": "Historical revenue CAGR, clamped [−30%, +50%]"},
            {"label": "Base FCFF", "value": format_inr(dcf.base_fcff),
             "note": "Median of last 5Y FCFF = NOPAT + D&A − CapEx − ΔNWC"},
        ]
    fin = bundle.valuation.financial_result
    if fin:
        rows += [
            {"label": "Justified P/B", "value": f"{fin.justified_pb:.2f}×",
             "note": "(ROE − g)/(Ke − g) — CFA L2 Equity, Reading 25"},
            {"label": "Sustainable growth", "value": _pct(fin.growth_rate, 1),
             "note": "capped terminal assumption, kept safely below Ke"},
        ]
    rows.append({"label": "Rating bands", "value": "BUY ≥ +15% · HOLD −10%…+15% · SELL < −10%",
                 "note": "Standard sell-side convention on 12-month upside"})
    return rows


# ---------------------------------------------------------------------------
# Reports archive index
# ---------------------------------------------------------------------------


def _update_report_index(output_dir: Path, entry: dict) -> None:
    index_path = output_dir / "_index.json"
    try:
        entries = json.loads(index_path.read_text()) if index_path.exists() else []
    except (json.JSONDecodeError, OSError):
        entries = []
    entries = [e for e in entries if e.get("filename") != entry["filename"]]
    entries.insert(0, entry)
    index_path.write_text(json.dumps(entries[:200], indent=1))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_report(
    ticker: str,
    provider: DataProvider,
    config: AppConfig,
    bundle: ResearchBundle | None = None,
    on_progress=None,
) -> Path:
    """Run the pipeline (unless a bundle is supplied) and render the PDF.

    Args:
        ticker:      NSE ticker with or without .NS suffix.
        provider:    Market data provider.
        config:      Loaded AppConfig.
        bundle:      Optional pre-computed ResearchBundle (skips re-analysis).
        on_progress: Optional callable(step: str) for SSE progress streaming.

    Returns:
        Path to the generated PDF (or .html if WeasyPrint libs are missing).
    """
    def progress(step: str) -> None:
        if on_progress:
            on_progress(step)

    ticker_ns = _normalize_ticker(ticker)
    base_ticker = ticker_ns.replace(".NS", "")
    logger.info("Generating report for %s …", ticker_ns)

    # ── 1. Fetch ─────────────────────────────────────────────────────────
    progress("Fetching financial data")
    profile = provider.get_profile(ticker_ns)
    financials = provider.get_financials(ticker_ns)
    prices = provider.get_prices(ticker_ns, period="3y")
    benchmark = provider.get_prices("^NSEI", period="3y")

    # ── 2. Analysis ──────────────────────────────────────────────────────
    if bundle is None:
        progress("Computing valuation models")
        bundle = run_research_pipeline(profile, financials, provider, config)
    progress("Running quality screens (Piotroski, Beneish, Altman)")

    c = bundle.conviction
    price = profile.get("current_price")

    # ── 3. Charts ────────────────────────────────────────────────────────
    progress("Rendering charts")
    chart_ctx = {
        "price": _b64(charts.price_vs_benchmark_chart(prices, benchmark, base_ticker)),
        "rev_ebitda": _b64(charts.revenue_ebitda_chart(financials["income"])),
        "pat_eps": _b64(charts.pat_eps_chart(financials["income"])),
        "dupont": _b64(charts.dupont_chart(bundle.dupont.years)),
        "earnings_quality": _b64(charts.earnings_quality_chart(bundle.accruals.cfo_ni_series)),
        "ccc": _b64(charts.ccc_chart(bundle.ccc)),
        "roic": _b64(charts.roic_wacc_chart(
            bundle.value_driver.roic_series, bundle.value_driver.wacc))
        if bundle.value_driver and bundle.value_driver.roic_series else "",
    }

    # ── 4. Context ───────────────────────────────────────────────────────
    rating_css = {"BUY": "buy", "SELL": "sell", "HOLD": "hold", "NR": "nr"}[c.rating]
    conf_score = c.confidence_score
    conf_color = "#1A7F4B" if conf_score >= 70 else ("#E67E22" if conf_score >= 40 else "#C0392B")
    conf_verdict = ("High conviction" if conf_score >= 70
                    else "Moderate conviction" if conf_score >= 40 else "Low conviction")
    conf_narrative = "; ".join(
        f"{comp.name}: {'+' if comp.points >= 0 else ''}{comp.points}"
        for comp in c.confidence_components) + "."

    dcf = bundle.valuation.dcf_result
    nifty500 = getattr(provider, "_load_nifty500", lambda: None)()
    ticker_names: dict[str, str] = {}
    if nifty500 is not None:
        ticker_names = dict(zip(nifty500["ticker"].str.upper(), nifty500["company_name"]))

    bank_rows = None
    fin = bundle.valuation.financial_result
    if fin:
        bm = fin.bank_metrics
        bank_rows = [
            {"label": "Justified P/B", "value": f"{fin.justified_pb:.2f}×"},
            {"label": "Return on tangible equity", "value": _pct(fin.roe)},
            {"label": "Cost of equity (Ke)", "value": _pct(fin.cost_of_equity)},
            {"label": "ROE − Ke spread", "value": _signed_pct(fin.roe_ke_spread)},
            {"label": "Tangible book / share", "value": _rs(fin.book_value_per_share, 0)},
            {"label": "Net interest margin (approx)", "value": _pct(bm.net_interest_margin) if bm.net_interest_margin else NA},
            {"label": "GNPA / PCR / CASA / CRAR", "value": "N/A (regulatory filings)"},
        ]

    sotp_rows = None
    sotp_total = None
    if bundle.valuation.sotp_result:
        s = bundle.valuation.sotp_result
        sotp_rows = [{
            "name": seg.name, "share": _pct(seg.ebitda_share, 0),
            "multiple": _x(seg.ev_ebitda_multiple),
            "ebitda": _cr(seg.segment_ebitda), "ev": _cr(seg.segment_ev),
        } for seg in s.segments]
        sotp_total = _cr(s.equity_value)

    india_fmt = None
    india = bundle.valuation.india_result
    if india:
        india_fmt = {
            "is_psu": "Yes" if india.is_psu else "No",
            "psu_discount": f"−{india.psu_discount_pct*100:.0f}%" if india.psu_discount_pct > 0 else "—",
            "group_adjustment": _signed_pct(india.group_adjustment_pct),
            "promoter_score": f"{india.promoter_score:.0f}/100",
            "promoter_premium": _signed_pct(india.promoter_premium_pct),
            "earnings_quality": f"{india.earnings_quality_score:.0f}/100",
            "cfo_ebitda": _pct(india.cfo_ebitda_ratio),
        }

    beneish_vars = [(k, f"{v:.3f}" if v is not None else NA)
                    for k, v in bundle.beneish.variables.items()]

    context = {
        "meta": {
            "ticker": base_ticker,
            "name": profile.get("long_name") or base_ticker,
            "sector": profile.get("sector") or "—",
            "industry": profile.get("industry") or "—",
            "mcap_band": _mcap_band(profile.get("market_cap")),
            "report_date": datetime.date.today().strftime("%d %b %Y"),
        },
        "rating": {
            "label": c.rating, "css": rating_css,
            "cmp": _rs(price, 2) if price else NA,
            "target": _rs(c.target_price, 0) if c.target_price else NA,
            "upside": _signed_pct(c.upside_pct),
            "upside_css": "up" if (c.upside_pct or 0) >= 0 else "down",
        },
        "thesis": _build_thesis(profile, bundle),
        "summary_bullets": _build_summary_bullets(profile, bundle),
        "stats": _build_stats(profile, bundle),
        "val": {
            "primary_label": _MODEL_LABELS.get(c.primary_model, c.primary_model),
            "primary_value": _rs(c.primary_value, 0) if c.primary_value else NA,
            "secondary_label": c.secondary_model,
            "secondary_value": _rs(c.secondary_value, 0) if c.secondary_value else NA,
            "bear": _rs(c.bear_value, 0) if c.bear_value else NA,
            "base": _rs(c.target_price, 0) if c.target_price else NA,
            "bull": _rs(c.bull_value, 0) if c.bull_value else NA,
            "bear_vs": _signed_pct(safe_divide((c.bear_value - price) if c.bear_value and price else None, price)),
            "bull_vs": _signed_pct(safe_divide((c.bull_value - price) if c.bull_value and price else None, price)),
            "route_reason": bundle.valuation.route_reason,
            "broker_row": bundle.valuation.broker_target_price is not None,
            "broker_target": _rs(bundle.valuation.broker_target_price, 0) if bundle.valuation.broker_target_price else NA,
            "broker_n": bundle.valuation.broker_analyst_count or "?",
            "wacc_label": _pct(dcf.wacc, 2) if dcf else NA,
            "tg_label": _pct(dcf.terminal_growth, 1) if dcf else NA,
        },
        "conf": {"score": conf_score, "color": conf_color,
                 "verdict": conf_verdict, "narrative": conf_narrative},
        "charts": chart_ctx,
        "sensitivity_html": _sensitivity_html(dcf.sensitivity) if dcf is not None else "",
        "fin_table": _financial_summary_table(financials, bundle, profile, config),
        "fin_note": "FY26E/FY27E are model estimates: revenue at Stage-1 growth, margins held at latest-year levels.",
        "bank": bank_rows,
        "dupont": _dupont_table(bundle),
        "piotroski": bundle.piotroski,
        "earnings_quality": _earnings_quality_section(bundle),
        "accruals_flags": bundle.accruals.flags + bundle.ccc.flags,
        "caq": {"score": bundle.caq.score, "max": bundle.caq.max_score,
                "components": bundle.caq.components},
        "gpa": {
            "latest": f"{bundle.gross_profitability.latest:.2f}" if bundle.gross_profitability.latest is not None else NA,
            "percentile": f"{bundle.gross_profitability.percentile:.0f}th"
            if bundle.gross_profitability.percentile is not None else "n/a (peer statements unavailable)",
        },
        "comps": _comps_section(bundle, profile, ticker_names),
        "sotp_rows": sotp_rows,
        "sotp_total": sotp_total,
        "india": india_fmt,
        "beneish": {
            "m_score": f"{bundle.beneish.m_score:.2f}" if bundle.beneish.m_score is not None else NA,
            "flagged": bool(bundle.beneish.flagged),
            "variables": beneish_vars,
            "missing": ", ".join(bundle.beneish.missing),
        },
        "altman": {
            "applicable": bundle.altman.applicable,
            "z": f"{bundle.altman.z_score:.2f}" if bundle.altman.z_score is not None else NA,
            "z_score": bundle.altman.z_score,
            "zone": bundle.altman.zone,
            "zone_css": {"Safe": "green", "Grey": "amber", "Distress": "red"}.get(bundle.altman.zone, "na"),
            "x1": _x(bundle.altman.x1, 2), "x2": _x(bundle.altman.x2, 2),
            "x3": _x(bundle.altman.x3, 2), "x4": _x(bundle.altman.x4, 2),
        },
        "governance": bundle.governance.metrics,
        "risks": _risk_factors(profile, bundle),
        "appendix": _appendix_tables(financials),
        "assumptions": _assumptions(bundle, config),
    }

    # ── 5. Render ────────────────────────────────────────────────────────
    progress("Rendering PDF")
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)
    html = env.get_template("report.html.j2").render(**context)

    output_dir = Path(os.getenv("REPORT_OUTPUT_DIR", config.report.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.date.today().strftime("%Y%m%d")
    pdf_path = output_dir / f"{base_ticker}_equity_research_{date_str}.pdf"

    index_entry = {
        "ticker": base_ticker,
        "name": profile.get("long_name") or base_ticker,
        "sector": profile.get("sector"),
        "rating": c.rating,
        "cmp": price,
        "target_price": c.target_price,
        "upside_pct": c.upside_pct,
        "confidence": c.confidence_score,
        "model": c.primary_model,
        "date": datetime.date.today().isoformat(),
        "filename": pdf_path.name,
    }

    try:
        _write_pdf(html, pdf_path)
        logger.info("PDF written: %s (%d KB)", pdf_path, pdf_path.stat().st_size // 1024)
        _update_report_index(output_dir, index_entry)
        return pdf_path
    except Exception as exc:  # noqa: BLE001
        html_path = pdf_path.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")
        index_entry["filename"] = html_path.name
        _update_report_index(output_dir, index_entry)
        logger.warning(
            "WeasyPrint failed (%s). HTML report written to %s\n"
            "Install system deps: brew install pango cairo gdk-pixbuf libffi", exc, html_path,
        )
        return html_path
