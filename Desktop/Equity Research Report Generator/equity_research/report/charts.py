"""Matplotlib chart generators — return PNG bytes for embedding in the report."""

from __future__ import annotations

import io
import logging

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

matplotlib.use("Agg")   # non-interactive backend; safe for server / subprocess use

logger = logging.getLogger(__name__)

_NAVY = "#1e3a5f"
_BLUE = "#2980b9"
_GREEN = "#27ae60"
_RED = "#e74c3c"
_ORANGE = "#f39c12"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=130, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _empty_chart(message: str, figsize: tuple) -> bytes:
    fig, ax = plt.subplots(figsize=figsize)
    ax.text(0.5, 0.5, message, ha="center", va="center",
            transform=ax.transAxes, fontsize=11, color="#aaa")
    ax.set_axis_off()
    return _to_bytes(fig)


# ---------------------------------------------------------------------------
# Public chart functions
# ---------------------------------------------------------------------------


def price_history_chart(
    prices: pd.DataFrame,
    ticker: str = "",
    figsize: tuple = (10, 4),
) -> bytes:
    """Closing price line with 52-week high/low reference lines.

    Args:
        prices: OHLCV DataFrame with DatetimeIndex (from DataProvider.get_prices).
        ticker: Company ticker used in the chart title.
        figsize: Matplotlib figure size (width, height) in inches.

    Returns:
        PNG image as bytes.
    """
    if prices.empty or "Close" not in prices.columns:
        return _empty_chart(f"{ticker} — No price data available", figsize)

    close = prices["Close"].dropna()
    if close.empty:
        return _empty_chart(f"{ticker} — No price data available", figsize)

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(close.index, close.values, color=_NAVY, linewidth=1.5, label="Close Price")

    trailing = close.tail(252)
    if len(trailing) >= 10:
        h52 = trailing.max()
        l52 = trailing.min()
        ax.axhline(h52, color=_GREEN, linestyle="--", linewidth=0.9, alpha=0.8,
                   label=f"52W High  ₹{h52:,.0f}")
        ax.axhline(l52, color=_RED,   linestyle="--", linewidth=0.9, alpha=0.8,
                   label=f"52W Low   ₹{l52:,.0f}")
        ax.fill_between(close.index, l52, h52, alpha=0.04, color=_BLUE)

    ax.set_title(f"{ticker} — Price History", fontsize=11, fontweight="bold", color=_NAVY, pad=8)
    ax.set_ylabel("Price (₹)", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"₹{v:,.0f}"))
    ax.legend(fontsize=8, loc="upper left", framealpha=0.8)
    ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return _to_bytes(fig)


def revenue_margin_chart(
    income: pd.DataFrame,
    figsize: tuple = (10, 4),
) -> bytes:
    """Dual-axis bar/line chart: revenue (bars, left) and three margin lines (right).

    Args:
        income: Normalized income statement DataFrame (index=year, columns include
                total_revenue, gross_profit, operating_income, net_income).
        figsize: Matplotlib figure size.

    Returns:
        PNG image as bytes.
    """
    if income.empty or "total_revenue" not in income.columns:
        return _empty_chart("Revenue & Margin — No data available", figsize)

    rev = income["total_revenue"].dropna() / 1e7   # → Crores
    if rev.empty:
        return _empty_chart("Revenue & Margin — No data available", figsize)

    years = rev.index.tolist()
    x = list(range(len(years)))

    fig, ax1 = plt.subplots(figsize=figsize)
    ax1.bar(x, rev.values, color=_NAVY, alpha=0.70, width=0.5, label="Revenue (₹ Cr)")
    ax1.set_ylabel("Revenue (₹ Crores)", fontsize=9, color=_NAVY)
    ax1.tick_params(axis="y", labelcolor=_NAVY, labelsize=8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(y) for y in years], fontsize=8)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    ax2 = ax1.twinx()
    margin_defs = [
        ("gross_profit",     _BLUE,   "Gross Margin"),
        ("operating_income", _ORANGE, "Op. Margin"),
        ("net_income",       _GREEN,  "Net Margin"),
    ]
    for col, color, label in margin_defs:
        if col in income.columns:
            mg = (income[col] / income["total_revenue"]).reindex(rev.index) * 100
            valid = mg.dropna()
            if not valid.empty:
                xi = [years.index(y) for y in valid.index if y in years]
                ax2.plot(xi, valid.values, color=color, linewidth=1.8,
                         marker="o", markersize=4, label=label)

    ax2.set_ylabel("Margin (%)", fontsize=9, color="#555")
    ax2.tick_params(axis="y", labelcolor="#555", labelsize=8)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    ax2.set_ylim(0, max(55, ax2.get_ylim()[1] * 1.15))

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left", framealpha=0.8)

    ax1.set_title("Revenue & Margin Trend", fontsize=11, fontweight="bold", color=_NAVY, pad=8)
    ax1.spines[["top", "right"]].set_visible(False)
    ax2.spines["top"].set_visible(False)
    fig.tight_layout()
    return _to_bytes(fig)
