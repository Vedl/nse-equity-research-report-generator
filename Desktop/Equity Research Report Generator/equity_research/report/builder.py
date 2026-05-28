"""PDF report builder — orchestrates the full analysis pipeline and renders the report.

Entry point: ``generate_report(ticker, provider, config) -> Path``

WeasyPrint is invoked in a child subprocess so that ``DYLD_LIBRARY_PATH`` (required
on macOS with Homebrew-installed pango) can be set before the process's dynamic
linker resolves the shared libraries.  If WeasyPrint is unavailable the function
falls back to writing an HTML file.
"""

from __future__ import annotations

import base64
import datetime
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

from equity_research.analysis.comps import CompsResult, compute_comps
from equity_research.analysis.dcf import DCFResult, run_dcf
from equity_research.analysis.ratios import compute_ratios
from equity_research.analysis.valuation import ValuationSummary, valuation_summary
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider
from equity_research.data.yfinance_provider import _normalize_ticker
from equity_research.report.charts import price_history_chart, revenue_margin_chart
from equity_research.utils.formatting import (
    NA,
    fmt_inr,
    fmt_pct,
    fmt_x,
    safe_divide,
)

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Subprocess PDF writer (avoids macOS dyld issues with Homebrew pango)
# ---------------------------------------------------------------------------


def _make_env_with_brew_libs() -> dict[str, str]:
    """Return os.environ augmented with the Homebrew lib directory."""
    env = os.environ.copy()
    try:
        result = subprocess.run(
            ["brew", "--prefix"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            brew_lib = f"{result.stdout.strip()}/lib"
            existing = env.get("DYLD_LIBRARY_PATH", "")
            env["DYLD_LIBRARY_PATH"] = f"{brew_lib}:{existing}" if existing else brew_lib
    except Exception:   # noqa: BLE001
        pass
    return env


def _write_pdf(html: str, pdf_path: Path) -> None:
    """Write *html* as a PDF at *pdf_path* via a WeasyPrint subprocess."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(html)
        tmp_html = fh.name

    script = (
        f"from weasyprint import HTML; "
        f"HTML(filename={repr(tmp_html)}).write_pdf({repr(str(pdf_path))})"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=_make_env_with_brew_libs(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
    finally:
        os.unlink(tmp_html)


# ---------------------------------------------------------------------------
# Data-formatting helpers (convert raw values to display strings)
# ---------------------------------------------------------------------------


def _na(v: Any) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return NA
    return str(v)


def _fmt_cr(v: Any) -> str:
    """Format a raw INR value as Crores string."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return NA
    return f"{float(v)/1e7:,.0f}"


def _fmt_pct_opt(v: Any) -> str:
    return fmt_pct(float(v)) if v is not None else NA


def _fin_table(
    df: pd.DataFrame,
    row_defs: list[tuple[str, str, bool]],
    n_years: int = 4,
) -> dict:
    """
    Build a financial table dict for the Jinja2 template.

    row_defs: list of (label, column_name, is_margin_row)
    """
    years = df.index.tolist()[-n_years:]
    rows = []
    for label, col, is_margin in row_defs:
        if col not in df.columns:
            values = [NA] * len(years)
        else:
            values = []
            for y in years:
                v = df.loc[y, col] if y in df.index else None
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    values.append(NA)
                elif is_margin:
                    values.append(f"{float(v)*100:.1f}%")
                else:
                    values.append(f"{float(v)/1e7:,.0f}")
        rows.append({"label": label, "vals": values, "is_margin": is_margin})
    return {"years": [str(y) for y in years], "rows": rows}


def _fmt_income(income: pd.DataFrame, balance: pd.DataFrame) -> dict:
    rev = income.get("total_revenue", pd.Series())
    gp  = income.get("gross_profit",  pd.Series())

    def margin_row(label, num_col):
        if num_col not in income.columns or "total_revenue" not in income.columns:
            return (label, "__none__", True)
        # Compute margin column
        col = f"__mg_{num_col}__"
        income[col] = income[num_col] / income["total_revenue"]
        return (label, col, True)

    defs = [
        ("Revenue",              "total_revenue",  False),
        ("Gross Profit",         "gross_profit",   False),
        margin_row("  Gross Margin",     "gross_profit"),
        ("EBITDA",               "ebitda",         False),
        margin_row("  EBITDA Margin",    "ebitda"),
        ("Operating Income",     "operating_income", False),
        margin_row("  Operating Margin", "operating_income"),
        ("Net Income",           "net_income",     False),
        margin_row("  Net Margin",       "net_income"),
    ]

    # EPS row (already per-share, not in Crores)
    years = income.index.tolist()[-4:]
    eps_vals = []
    for y in years:
        v = income.loc[y, "basic_eps"] if "basic_eps" in income.columns and y in income.index else None
        if v is None or (isinstance(v, float) and math.isnan(v)):
            eps_vals.append(NA)
        else:
            eps_vals.append(f"₹{float(v):.2f}")

    table = _fin_table(income, defs)
    table["rows"].append({"label": "EPS (₹ per share)", "vals": eps_vals, "is_margin": False})
    return table


def _fmt_balance(balance: pd.DataFrame) -> dict:
    defs = [
        ("Total Assets",         "total_assets",        False),
        ("Cash & Equivalents",   "cash_and_equivalents", False),
        ("Accounts Receivable",  "accounts_receivable",  False),
        ("Inventory",            "inventory",            False),
        ("Current Assets",       "current_assets",       False),
        ("Current Liabilities",  "current_liabilities",  False),
        ("Total Debt",           "total_debt",           False),
        ("Stockholders' Equity", "stockholders_equity",  False),
    ]
    return _fin_table(balance, defs)


def _fmt_cashflow(cashflow: pd.DataFrame) -> dict:
    defs = [
        ("Operating Cash Flow",  "operating_cash_flow",      False),
        ("Capital Expenditure",  "capital_expenditure",      False),
        ("Free Cash Flow",       "free_cash_flow",           False),
        ("D&A",                  "depreciation_amortization", False),
    ]
    return _fin_table(cashflow, defs)


def _fmt_ratios(ratios: dict) -> dict:
    p = ratios.get("profitability", {})
    l = ratios.get("liquidity", {})
    s = ratios.get("solvency", {})
    e = ratios.get("efficiency", {})
    c = ratios.get("cagr", {})
    return {
        "gross_margin":      fmt_pct(p.get("gross_margin")),
        "operating_margin":  fmt_pct(p.get("operating_margin")),
        "net_margin":        fmt_pct(p.get("net_margin")),
        "roe":               fmt_pct(p.get("roe")),
        "roic":              fmt_pct(p.get("roic")),
        "current_ratio":     fmt_x(l.get("current_ratio")),
        "quick_ratio":       fmt_x(l.get("quick_ratio")),
        "debt_to_equity":    fmt_x(s.get("debt_to_equity")),
        "interest_coverage": fmt_x(s.get("interest_coverage")),
        "asset_turnover":    fmt_x(e.get("asset_turnover")),
        "revenue_3y":        fmt_pct(c.get("revenue_3y")),
        "revenue_5y":        fmt_pct(c.get("revenue_5y")),
        "eps_3y":            fmt_pct(c.get("eps_3y")),
        "eps_5y":            fmt_pct(c.get("eps_5y")),
    }


def _fmt_snap(profile: dict) -> dict:
    return {
        "current_price": f"₹{profile['current_price']:,.2f}" if profile.get("current_price") else NA,
        "market_cap":    fmt_inr(profile.get("market_cap")),
        "high_52w":      f"₹{profile['fifty_two_week_high']:,.2f}" if profile.get("fifty_two_week_high") else NA,
        "low_52w":       f"₹{profile['fifty_two_week_low']:,.2f}"  if profile.get("fifty_two_week_low")  else NA,
        "beta":          fmt_x(profile.get("beta"), suffix=""),
        "pe":            fmt_x(profile.get("trailing_pe")),
        "pb":            fmt_x(profile.get("price_to_book")),
        "div_yield":     fmt_pct(profile.get("dividend_yield")),
    }


def _fmt_dcf(dcf: DCFResult, profile: dict, config: AppConfig) -> dict:
    wc = dcf.wacc_components
    cp = profile.get("current_price") or 0.0
    upside = safe_divide(dcf.intrinsic_value_per_share - cp, cp)
    return {
        "rf":          fmt_pct(config.market.risk_free_rate),
        "erp":         fmt_pct(config.market.equity_risk_premium),
        "beta":        f"{profile.get('beta') or 1.0:.2f}",
        "ke":          fmt_pct(wc.cost_of_equity),
        "kd_pre":      fmt_pct(wc.cost_of_debt_pretax),
        "kd_post":     fmt_pct(wc.cost_of_debt_aftertax),
        "tax":         fmt_pct(config.market.tax_rate),
        "eq_wt":       fmt_pct(wc.equity_weight),
        "dbt_wt":      fmt_pct(wc.debt_weight),
        "wacc":        fmt_pct(wc.wacc),
        "growth":      fmt_pct(dcf.growth_rate),
        "fcff_margin": fmt_pct(dcf.fcff_margin),
        "terminal_g":  fmt_pct(dcf.terminal_growth),
        "pv_fcff_sum": f"{sum(dcf.pv_fcff)/1e7:,.0f}",
        "pv_tv":       f"{dcf.pv_terminal_value/1e7:,.0f}",
        "ev":          f"{dcf.enterprise_value/1e7:,.0f}",
        "net_debt":    f"{dcf.net_debt/1e7:,.0f}",
        "equity_val":  f"{dcf.equity_value/1e7:,.0f}",
        "shares":      f"{dcf.shares_outstanding/1e7:,.2f}",
        "intrinsic":   f"₹{dcf.intrinsic_value_per_share:,.2f}",
        "dcf_upside":  f"{upside*100:+.1f}%" if upside is not None else NA,
    }


def _fmt_dcf_proj(dcf: DCFResult) -> list[dict]:
    rows = []
    for i, (fcff, pv) in enumerate(zip(dcf.projected_fcff, dcf.pv_fcff), start=1):
        rows.append({
            "year":    f"Y{i}",
            "fcff":    f"{fcff/1e7:,.0f}",
            "pv_fcff": f"{pv/1e7:,.0f}",
        })
    return rows


def _sensitivity_html(df: pd.DataFrame) -> str:
    """Render the sensitivity DataFrame as a color-coded HTML table."""
    if df.empty:
        return "<p class='na'>Sensitivity table unavailable.</p>"

    try:
        center = df.iloc[len(df) // 2, len(df.columns) // 2]
    except Exception:
        center = None

    def cell_class(v: float) -> str:
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
    body_rows = []
    for idx_label, row in df.iterrows():
        cells = f"<th>{idx_label}</th>"
        for v in row:
            if v is None or (isinstance(v, float) and math.isnan(v)):
                cells += '<td class="s-na">n/a</td>'
            else:
                cls = cell_class(float(v))
                cells += f'<td class="{cls}">₹{float(v):,.0f}</td>'
        body_rows.append(f"<tr>{cells}</tr>")

    return (
        '<table class="sens-table"><thead>' + header + "</thead><tbody>"
        + "\n".join(body_rows) + "</tbody></table>"
    )


def _fmt_comps_implied(
    comps: CompsResult, current_price: float
) -> list[dict]:
    rows = []
    for label, val in [
        ("From P/E",        comps.implied_pe),
        ("From EV/EBITDA",  comps.implied_ev_ebitda),
        ("From P/B",        comps.implied_pb),
        ("From EV/Sales",   comps.implied_ev_sales),
    ]:
        if val is None:
            rows.append({"label": label, "price": NA, "upside": NA, "css": "na"})
        else:
            up = safe_divide(val - current_price, current_price)
            rows.append({
                "label": label,
                "price": f"₹{val:,.0f}",
                "upside": f"{up*100:+.1f}%" if up is not None else NA,
                "css": "up" if (up or 0) >= 0 else "down",
            })
    return rows


def _fmt_val_summary(val: ValuationSummary) -> dict:
    """Pre-format ValuationSummary into display strings for the template."""
    def _price(v):
        return f"₹{v:,.0f}" if v is not None else NA

    def _upside(v):
        return f"{v*100:+.1f}%" if v is not None else NA

    return {
        "dcf_price":       _price(val.dcf_value),
        "dcf_upside":      _upside(val.dcf_upside_pct),
        "dcf_css":         "up" if (val.dcf_upside_pct or 0) >= 0 else "down",
        "comps_range":     (
            f"₹{val.comps_low:,.0f} – ₹{val.comps_high:,.0f}"
            if val.comps_low is not None and val.comps_high is not None else NA
        ),
        "comps_upside":    f"{val.comps_upside_pct*100:+.1f}% (median)" if val.comps_upside_pct is not None else NA,
        "comps_css":       "up" if (val.comps_upside_pct or 0) >= 0 else "down",
        "current_price":   _price(val.current_price),
        "has_dcf":         val.dcf_value is not None,
        "has_comps":       val.comps_median is not None,
    }


def _to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_report(
    ticker: str,
    provider: DataProvider,
    config: AppConfig,
) -> Path:
    """Run the full analysis pipeline and write a PDF (or HTML) report.

    Args:
        ticker:   NSE ticker with or without the .NS suffix.
        provider: DataProvider instance for market data.
        config:   Loaded AppConfig (all macro assumptions and output settings).

    Returns:
        Path to the generated PDF (or .html fallback).
    """
    ticker_ns = _normalize_ticker(ticker)
    base_ticker = ticker_ns.replace(".NS", "")

    logger.info("Generating report for %s …", ticker_ns)

    # ── 1. Fetch ──────────────────────────────────────────────────────────
    profile = provider.get_profile(ticker_ns)
    financials = provider.get_financials(ticker_ns)
    prices = provider.get_prices(ticker_ns, period=config.report.charts.price_history_period)

    # ── 2. Analysis ───────────────────────────────────────────────────────
    ratios = compute_ratios(
        financials["income"],
        financials["balance_sheet"],
        financials["cash_flow"],
        tax_rate=config.market.tax_rate,
    )

    dcf_result: DCFResult | None = None
    try:
        dcf_result = run_dcf(profile, financials, config)
    except (ValueError, ZeroDivisionError) as exc:
        logger.warning("DCF skipped: %s", exc)

    comps_result: CompsResult | None = None
    try:
        comps_result = compute_comps(profile, financials, provider, config)
    except Exception as exc:   # noqa: BLE001
        logger.warning("Comps skipped: %s", exc)

    current_price = float(profile.get("current_price") or 0.0)
    val_summary = valuation_summary(current_price, dcf_result, comps_result)

    # ── 3. Charts ─────────────────────────────────────────────────────────
    figsize = tuple(config.report.charts.figsize)
    price_bytes  = price_history_chart(prices, base_ticker, figsize)
    margin_bytes = revenue_margin_chart(financials["income"], figsize)

    # ── 4. Build template context ─────────────────────────────────────────
    income_copy = financials["income"].copy()
    context: dict = {
        "ticker":       base_ticker,
        "report_date":  datetime.date.today().strftime("%d %B %Y"),
        "profile":      profile,
        "snap":         _fmt_snap(profile),
        "income_data":  _fmt_income(income_copy, financials["balance_sheet"]),
        "balance_data": _fmt_balance(financials["balance_sheet"]),
        "cashflow_data":_fmt_cashflow(financials["cash_flow"]),
        "ratios":       ratios,
        "rfmt":         _fmt_ratios(ratios),
        "dcf":          dcf_result,
        "dcf_fmt":      _fmt_dcf(dcf_result, profile, config) if dcf_result else {},
        "dcf_proj_table": _fmt_dcf_proj(dcf_result) if dcf_result else [],
        "sensitivity_html": _sensitivity_html(dcf_result.sensitivity) if dcf_result else "",
        "comps":        comps_result,
        "comps_implied_rows": _fmt_comps_implied(comps_result, current_price) if comps_result else [],
        "valuation":    val_summary,
        "vfmt":         _fmt_val_summary(val_summary),
        "price_chart_b64":  _to_b64(price_bytes),
        "margin_chart_b64": _to_b64(margin_bytes),
        "config":       config,
    }

    # ── 5. Render HTML ────────────────────────────────────────────────────
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)
    tmpl = env.get_template("report.html.j2")
    html = tmpl.render(**context)

    # ── 6. Write PDF ──────────────────────────────────────────────────────
    output_dir = Path(config.report.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.date.today().strftime("%Y%m%d")
    pdf_path = output_dir / f"{base_ticker}_equity_research_{date_str}.pdf"

    try:
        _write_pdf(html, pdf_path)
        logger.info("PDF written: %s  (%d KB)", pdf_path, pdf_path.stat().st_size // 1024)
        return pdf_path
    except Exception as exc:   # noqa: BLE001
        html_path = pdf_path.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")
        logger.warning(
            "WeasyPrint failed (%s). HTML report written to %s\n"
            "Install system deps: brew install pango cairo gdk-pixbuf libffi",
            exc, html_path,
        )
        return html_path
