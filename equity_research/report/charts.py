"""Matplotlib chart suite for the research report — SVG output, shared style.

Every chart:
* returns SVG bytes (vector — crisp at any print resolution in WeasyPrint),
* applies the module-level ``research_style`` rcParams,
* carries axis labels, a title, and a "Source:" annotation,
* renders an explicit empty-state message when data is missing (never crashes).

Palette mirrors the report CSS: navy #0A2342, steel #4A5568, rule #CBD5E0.
"""

from __future__ import annotations

import io
import logging

import matplotlib

matplotlib.use("Agg")   # non-interactive backend; safe for server use

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

logger = logging.getLogger(__name__)

NAVY = "#0A2342"
STEEL = "#4A5568"
RULE = "#CBD5E0"
BLUE = "#1565C0"
GREEN = "#1A7F4B"
RED = "#C0392B"
AMBER = "#E67E22"
ROW_ALT = "#F7F9FC"

# Shared research chart style — applied at module load
research_style = {
    "font.family": "DejaVu Sans",
    "font.size": 8.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
    "axes.edgecolor": STEEL,
    "axes.labelcolor": STEEL,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlecolor": NAVY,
    "xtick.color": STEEL,
    "ytick.color": STEEL,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "grid.alpha": 0.3,
    "grid.color": RULE,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "legend.fontsize": 7.5,
    "legend.framealpha": 0.9,
    "legend.edgecolor": RULE,
    "svg.fonttype": "path",   # text → paths: renders identically everywhere
}
plt.rcParams.update(research_style)

_SOURCE = "Source: NSE / yfinance"


def _to_svg(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _annotate_source(fig: plt.Figure, text: str = _SOURCE) -> None:
    fig.text(0.01, -0.02, text, fontsize=6.5, color=STEEL, ha="left")


def _empty_chart(message: str, figsize: tuple = (7.2, 2.6)) -> bytes:
    fig, ax = plt.subplots(figsize=figsize)
    ax.text(0.5, 0.5, message, ha="center", va="center",
            transform=ax.transAxes, fontsize=10, color=STEEL)
    ax.set_axis_off()
    ax.grid(False)
    return _to_svg(fig)


def _fy(years: list[int]) -> list[str]:
    """Indian fiscal-year labels: calendar 2025 statements → FY25."""
    return [f"FY{int(y) % 100:02d}" for y in years]


# ---------------------------------------------------------------------------
# Page 2 — price vs benchmark (indexed)
# ---------------------------------------------------------------------------


def price_vs_benchmark_chart(
    prices: pd.DataFrame,
    benchmark: pd.DataFrame,
    ticker: str,
    figsize: tuple = (7.2, 2.7),
) -> bytes:
    """3-year price performance vs Nifty 50, both indexed to 100.

    The Nifty 50 price index (^NSEI) is used; Yahoo carries no TRI series —
    labelled honestly on the chart.
    """
    if prices.empty or "Close" not in prices.columns:
        return _empty_chart(f"{ticker} — price history unavailable", figsize)

    close = prices["Close"].dropna()
    if close.empty:
        return _empty_chart(f"{ticker} — price history unavailable", figsize)
    idx_stock = close / close.iloc[0] * 100

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(idx_stock.index, idx_stock.values, color=NAVY, linewidth=1.6,
            label=f"{ticker} ({idx_stock.values[-1]:.0f})")

    if not benchmark.empty and "Close" in benchmark.columns:
        bench = benchmark["Close"].dropna()
        if not bench.empty:
            # Align the start date to the stock series
            bench = bench[bench.index >= close.index[0]]
            if not bench.empty:
                idx_bench = bench / bench.iloc[0] * 100
                ax.plot(idx_bench.index, idx_bench.values, color=STEEL, linewidth=1.2,
                        label=f"Nifty 50 ({idx_bench.values[-1]:.0f})")

    ax.axhline(100, color=RULE, linewidth=0.8, linestyle="--")
    ax.set_title(f"{ticker} vs Nifty 50 — 3-year relative performance (indexed to 100)")
    ax.set_ylabel("Indexed return")
    ax.legend(loc="upper left")
    _annotate_source(fig, _SOURCE + " · ^NSEI price index (TRI unavailable via Yahoo)")
    return _to_svg(fig)


# ---------------------------------------------------------------------------
# Page 3 — revenue & EBITDA; PAT & EPS
# ---------------------------------------------------------------------------


def revenue_ebitda_chart(income: pd.DataFrame, figsize: tuple = (7.2, 2.7)) -> bytes:
    """Grouped Revenue/EBITDA bars (₹ Cr) with EBITDA-margin line overlay."""
    if income.empty or "total_revenue" not in income.columns:
        return _empty_chart("Revenue & EBITDA — data unavailable", figsize)

    frame = income[["total_revenue"]].copy()
    frame["ebitda"] = income.get("ebitda", pd.Series(dtype=float))
    frame = frame.dropna(subset=["total_revenue"]).tail(5)
    if frame.empty:
        return _empty_chart("Revenue & EBITDA — data unavailable", figsize)

    years = _fy(frame.index.tolist())
    x = range(len(years))
    rev_cr = frame["total_revenue"] / 1e7
    ebitda_cr = frame["ebitda"] / 1e7

    fig, ax1 = plt.subplots(figsize=figsize)
    w = 0.38
    ax1.bar([i - w / 2 for i in x], rev_cr.values, width=w, color=NAVY, label="Revenue")
    ax1.bar([i + w / 2 for i in x], ebitda_cr.fillna(0).values, width=w, color=BLUE,
            alpha=0.85, label="EBITDA")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(years)
    ax1.set_ylabel("₹ Crores")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    ax2 = ax1.twinx()
    margin = (frame["ebitda"] / frame["total_revenue"] * 100)
    valid = margin.dropna()
    if not valid.empty:
        xi = [list(frame.index).index(y) for y in valid.index]
        ax2.plot(xi, valid.values, color=AMBER, marker="o", markersize=4,
                 linewidth=1.6, label="EBITDA margin (RHS)")
        ax2.set_ylabel("EBITDA margin (%)")
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax2.set_ylim(0, max(40.0, float(valid.max()) * 1.3))
        ax2.grid(False)
        ax2.spines["top"].set_visible(False)

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left")
    ax1.set_title("Revenue & EBITDA trend")
    _annotate_source(fig)
    return _to_svg(fig)


def pat_eps_chart(income: pd.DataFrame, figsize: tuple = (7.2, 2.5)) -> bytes:
    """PAT bars (₹ Cr) with diluted-EPS line overlay (₹)."""
    if income.empty or "net_income" not in income.columns:
        return _empty_chart("PAT & EPS — data unavailable", figsize)
    frame = income[["net_income"]].dropna().tail(5)
    if frame.empty:
        return _empty_chart("PAT & EPS — data unavailable", figsize)

    years = _fy(frame.index.tolist())
    x = range(len(years))
    pat_cr = frame["net_income"] / 1e7

    fig, ax1 = plt.subplots(figsize=figsize)
    ax1.bar(list(x), pat_cr.values, width=0.5, color=NAVY, label="PAT")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(years)
    ax1.set_ylabel("PAT (₹ Crores)")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    eps_col = "diluted_eps" if "diluted_eps" in income.columns else "basic_eps"
    eps = income.get(eps_col, pd.Series(dtype=float)).reindex(frame.index).dropna()
    if not eps.empty:
        ax2 = ax1.twinx()
        xi = [list(frame.index).index(y) for y in eps.index]
        ax2.plot(xi, eps.values, color=GREEN, marker="o", markersize=4,
                 linewidth=1.6, label="Diluted EPS (RHS)")
        ax2.set_ylabel("EPS (₹)")
        ax2.grid(False)
        ax2.spines["top"].set_visible(False)
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, loc="upper left")
    ax1.set_title("PAT & diluted EPS trend")
    _annotate_source(fig)
    return _to_svg(fig)


# ---------------------------------------------------------------------------
# Page 4 — DuPont, earnings quality, CCC
# ---------------------------------------------------------------------------


def dupont_chart(dupont_years: list, figsize: tuple = (7.2, 2.6)) -> bytes:
    """ROE bars with EBIT-margin and asset-turnover overlays.

    Makes the *composition* of ROE visible: profitability (margin) vs
    efficiency (turnover); leverage is in the table alongside.
    """
    rows = [y for y in dupont_years if y.roe is not None]
    if not rows:
        return _empty_chart("DuPont decomposition — data unavailable", figsize)

    years = _fy([y.year for y in rows])
    x = range(len(rows))
    roe = [y.roe * 100 for y in rows]

    fig, ax1 = plt.subplots(figsize=figsize)
    ax1.bar(list(x), roe, width=0.5, color=NAVY, label="ROE")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(years)
    ax1.set_ylabel("ROE (%)")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    ax2 = ax1.twinx()
    margins = [(y.ebit_margin * 100 if y.ebit_margin is not None else None) for y in rows]
    turns = [(y.asset_turnover if y.asset_turnover is not None else None) for y in rows]
    if any(m is not None for m in margins):
        ax2.plot([i for i, m in zip(x, margins) if m is not None],
                 [m for m in margins if m is not None],
                 color=AMBER, marker="o", markersize=4, linewidth=1.5,
                 label="EBIT margin % (RHS)")
    if any(t is not None for t in turns):
        ax2.plot([i for i, t in zip(x, turns) if t is not None],
                 [t * 100 for t in turns if t is not None],
                 color=BLUE, marker="s", markersize=4, linewidth=1.5,
                 label="Asset turnover ×100 (RHS)")
    ax2.grid(False)
    ax2.spines["top"].set_visible(False)
    ax2.set_ylabel("Margin % / Turnover")

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", ncols=2)
    ax1.set_title("DuPont drivers — ROE, EBIT margin, asset turnover")
    _annotate_source(fig)
    return _to_svg(fig)


def earnings_quality_chart(
    cfo_ni_series: list[tuple[int, float]],
    figsize: tuple = (7.2, 2.4),
) -> bytes:
    """CFO/Net-Income bars with the 0.8 quality threshold line (Sloan 1996)."""
    if not cfo_ni_series:
        return _empty_chart("Earnings quality — data unavailable", figsize)

    years = _fy([y for y, _ in cfo_ni_series])
    vals = [v for _, v in cfo_ni_series]
    colors = [GREEN if v >= 0.8 else RED for v in vals]

    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(range(len(vals)), vals, width=0.5, color=colors)
    ax.axhline(0.8, color=RED, linewidth=1.0, linestyle="--", label="0.8 red-flag threshold")
    ax.axhline(1.0, color=STEEL, linewidth=0.8, linestyle=":")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years)
    ax.set_ylabel("CFO / Net Income")
    ax.legend(loc="lower right")
    ax.set_title("Earnings quality — cash conversion of profits")
    _annotate_source(fig)
    return _to_svg(fig)


def ccc_chart(ccc_result, figsize: tuple = (7.2, 2.5)) -> bytes:
    """DSO / DIO / DPO / CCC trend over five fiscal years."""
    if not ccc_result.years or all(c is None for c in ccc_result.ccc):
        return _empty_chart("Cash conversion cycle — data unavailable", figsize)

    years = _fy(ccc_result.years)
    x = range(len(years))

    fig, ax = plt.subplots(figsize=figsize)
    series = [
        ("DSO", ccc_result.dso, BLUE, "o"),
        ("DIO", ccc_result.dio, AMBER, "s"),
        ("DPO", ccc_result.dpo, STEEL, "^"),
        ("CCC", ccc_result.ccc, NAVY, "D"),
    ]
    for label, vals, color, marker in series:
        pts = [(i, v) for i, v in zip(x, vals) if v is not None]
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color,
                    marker=marker, markersize=4,
                    linewidth=2.0 if label == "CCC" else 1.2, label=label)
    ax.set_xticks(list(x))
    ax.set_xticklabels(years)
    ax.set_ylabel("Days")
    ax.legend(loc="upper left", ncols=4)
    ax.set_title("Working capital cycle — DSO + DIO − DPO")
    _annotate_source(fig)
    return _to_svg(fig)


def roic_wacc_chart(
    roic_series: list[tuple[int, float]],
    wacc: float,
    figsize: tuple = (7.2, 2.5),
) -> bytes:
    """5-year ROIC trend with the WACC hurdle line (McKinsey value-driver view)."""
    if not roic_series:
        return _empty_chart("ROIC vs WACC — data unavailable", figsize)

    years = _fy([y for y, _ in roic_series])
    vals = [v * 100 for _, v in roic_series]
    colors = [GREEN if v >= wacc * 100 else RED for v in vals]

    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(range(len(vals)), vals, width=0.5, color=colors)
    ax.axhline(wacc * 100, color=NAVY, linewidth=1.4, linestyle="--",
               label=f"WACC {wacc*100:.1f}%")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years)
    ax.set_ylabel("ROIC (%)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.legend(loc="upper left")
    ax.set_title("ROIC vs WACC — value creation test")
    _annotate_source(fig, _SOURCE + " · Koller et al. (McKinsey) value-driver framework")
    return _to_svg(fig)
