/**
 * Typed API client.
 *
 * URL strategy:
 *   Server-side (Node / Server Components): use absolute API_URL env var
 *     so Next.js doesn't throw "Failed to parse URL: /api/..."
 *   Browser (Client Components): use relative /api/* — the next.config.ts
 *     rewrite proxies these to the Railway backend.
 *
 * All responses are Zod-validated; a failed parse throws a ZodError which
 * the caller (TanStack Query + error boundary) surfaces as an error state.
 */

import {
  ResearchSchema,
  TickersSchema,
  PricesSchema,
  type Research,
  type TickerItem,
  type PriceBar,
} from "./schemas"

// Server: absolute URL from env.  Browser: relative (empty string = same origin).
const API_BASE =
  typeof window === "undefined"
    ? (process.env.API_URL ?? "http://localhost:8000")
    : ""

/** Normalise a ticker: upper-case, ensure .NS suffix. */
export function normaliseTicker(ticker: string): string {
  const t = ticker.toUpperCase().trim()
  return t.endsWith(".NS") ? t : `${t}.NS`
}

async function apiFetch(path: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}${path}`, {
    // next.js fetch cache — revalidate every 10 min to match backend TTLCache
    next: { revalidate: 600 },
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json()
}

export async function fetchResearch(ticker: string): Promise<Research> {
  const t = normaliseTicker(ticker)
  const raw = await apiFetch(`/api/research/${t}`)
  return ResearchSchema.parse(raw)
}

export async function fetchTickers(): Promise<TickerItem[]> {
  const raw = await apiFetch("/api/tickers")
  return TickersSchema.parse(raw)
}

export async function fetchPrices(
  ticker: string,
  period = "1y"
): Promise<PriceBar[]> {
  const t = normaliseTicker(ticker)
  const raw = await apiFetch(`/api/prices/${t}?period=${period}`)
  return PricesSchema.parse(raw)
}

export async function fetchHealth(): Promise<{ status: string }> {
  const raw = await apiFetch("/api/health")
  return raw as { status: string }
}
