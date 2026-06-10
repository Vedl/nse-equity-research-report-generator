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


def indian_group(value: float, decimals: int = 0) -> str:
    """Format a number with Indian digit grouping: 12345678 → '1,23,45,678'.

    The last three digits form one group; every two digits thereafter form a
    group (lakh/crore convention).
    """
    neg = value < 0
    s = f"{abs(value):.{decimals}f}"
    if "." in s:
        int_part, dec_part = s.split(".")
    else:
        int_part, dec_part = s, ""
    if len(int_part) > 3:
        head, tail = int_part[:-3], int_part[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        int_part = ",".join(groups + [tail])
    out = int_part + (f".{dec_part}" if dec_part else "")
    return f"-{out}" if neg else out


def format_inr(value: float | None, unit: str = "crore", decimals: int = 0) -> str:
    """Format a raw INR amount using Indian lakh/crore notation.

    Args:
        value:    Amount in full rupees (or per-share rupees for unit='rupee').
        unit:     'crore' → '₹X,XX,XXX Cr'; 'rupee' → '₹X,XXX.XX'.
        decimals: Decimal places for the displayed number.

    Returns:
        Formatted string, or 'n/a' for missing values.
    """
    import math

    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return NA
    if unit == "rupee":
        return f"₹{indian_group(value, decimals)}"
    cr = value / _CR
    return f"₹{indian_group(cr, decimals)} Cr"


def cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Compound annual growth rate from start to end over the given number of years."""
    if start is None or end is None or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1
