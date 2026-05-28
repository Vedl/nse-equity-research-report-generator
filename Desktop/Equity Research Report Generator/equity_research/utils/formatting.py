"""Formatting helpers for INR values, percentages, and missing-data sentinels."""

from __future__ import annotations

NA = "n/a"
_CR = 1e7   # 1 Crore = 10^7 INR


def safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    """Return numerator / denominator, or None if either is None/zero/NaN."""
    import math

    if numerator is None or denominator is None:
        return None
    if isinstance(numerator, float) and math.isnan(numerator):
        return None
    if isinstance(denominator, float) and math.isnan(denominator):
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def na_if_none(value: float | None) -> float | str:
    """Return the value as-is, or the string 'n/a' if None/NaN."""
    import math

    if value is None:
        return NA
    if isinstance(value, float) and math.isnan(value):
        return NA
    return value


def fmt_inr(value: float | None, decimals: int = 0) -> str:
    """Format a raw INR value (full rupees) as '₹X Cr' or 'n/a'."""
    import math

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return NA
    cr = value / _CR
    if abs(cr) >= 1_00_000:  # >= 1 lakh crore → show in lakh Cr
        return f"₹{cr / 1_00_000:.2f} L Cr"
    if abs(cr) >= 1:
        fmt = f"{{:,.{decimals}f}}"
        return f"₹{fmt.format(cr)} Cr"
    return f"₹{value:,.{decimals}f}"


def fmt_pct(value: float | None, decimals: int = 2) -> str:
    """Format a ratio (0–1 scale) as 'X.XX%' or 'n/a'."""
    import math

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return NA
    return f"{value * 100:.{decimals}f}%"


def fmt_x(value: float | None, decimals: int = 2, suffix: str = "x") -> str:
    """Format a multiple (e.g. P/E ratio) as 'X.XXx' or 'n/a'."""
    import math

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return NA
    return f"{value:.{decimals}f}{suffix}"


def fmt_cr(value: float | None, decimals: int = 0) -> str:
    """Format a value already in Crores as '₹X Cr' or 'n/a'."""
    import math

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return NA
    fmt = f"{{:,.{decimals}f}}"
    return f"₹{fmt.format(value)} Cr"


def cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Compound annual growth rate from start to end over the given number of years."""
    if start is None or end is None or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1
