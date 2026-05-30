/**
 * Formatting utilities for financial numbers.
 * All functions return strings safe for display; null/undefined → "—"
 */

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
  notation: "compact",
})

const CRORE = 1e7 // 1 Cr = 10^7

/** Format a raw INR value to "₹1,234 Cr". */
export function fmtCr(
  value: number | null | undefined,
  decimals = 0
): string {
  if (value == null || !isFinite(value)) return "—"
  const cr = value / CRORE
  return (
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(cr) + " Cr"
  )
}

/** Format a price in INR (e.g. ₹1,340). */
export function fmtINR(
  value: number | null | undefined,
  decimals = 2
): string {
  if (value == null || !isFinite(value)) return "—"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

/** Format a ratio/margin as a percentage (e.g. 12.3%). */
export function fmtPct(
  value: number | null | undefined,
  decimals = 1
): string {
  if (value == null || !isFinite(value)) return "—"
  return (
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value * 100) + "%"
  )
}

/** Format a trading multiple (e.g. "24.5x"). */
export function fmtMultiple(
  value: number | null | undefined,
  decimals = 1
): string {
  if (value == null || !isFinite(value) || value <= 0) return "—"
  return (
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value) + "x"
  )
}

/** Format USD market cap (e.g. "$189B"). */
export function fmtUSD(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return "—"
  return USD.format(value)
}

/** Format a raw number with 2dp and tabular spacing. */
export function fmtNum(
  value: number | null | undefined,
  decimals = 2
): string {
  if (value == null || !isFinite(value)) return "—"
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

/** Format EPS in INR (e.g. "₹24.50"). */
export function fmtEPS(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return "—"
  return fmtINR(value, 2)
}

/** Return "+12.3%" or "-4.5%" with sign — used for YoY growth badges. */
export function fmtDelta(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return "—"
  const sign = value >= 0 ? "+" : ""
  return sign + fmtPct(value)
}

/** Determine if a delta value is positive, negative, or neutral. */
export function deltaDirection(
  value: number | null | undefined
): "up" | "down" | "neutral" {
  if (value == null || !isFinite(value) || Math.abs(value) < 0.0001)
    return "neutral"
  return value > 0 ? "up" : "down"
}
