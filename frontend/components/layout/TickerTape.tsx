"use client"

import { useQuery } from "@tanstack/react-query"

interface IndexQuote {
  symbol: string
  label: string
  level: number
  change: number
  change_pct: number | null
}

async function fetchIndices(): Promise<IndexQuote[]> {
  const res = await fetch("/api/indices")
  if (!res.ok) throw new Error(`Indices fetch failed (${res.status})`)
  return res.json()
}

/**
 * Persistent live index strip — signals the product lives in the real market.
 * Polls the backend every 60 s (matching its server-side cache TTL).
 */
export function TickerTape() {
  const { data } = useQuery({
    queryKey: ["indices"],
    queryFn: fetchIndices,
    refetchInterval: 60_000,
    staleTime: 55_000,
  })

  if (!data || data.length === 0) return null

  return (
    <div className="w-full bg-[#0A2342] text-white">
      <div className="mx-auto flex h-7 max-w-7xl items-center gap-6 overflow-x-auto px-4 font-mono text-[11px] sm:px-6">
        {data.map((q) => {
          const up = (q.change ?? 0) >= 0
          return (
            <span key={q.symbol} className="flex shrink-0 items-center gap-2">
              <span className="font-medium tracking-wide text-slate-300">
                {q.label}
              </span>
              <span className="tabular-nums">
                {q.level.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </span>
              <span
                className={
                  up ? "tabular-nums text-emerald-400" : "tabular-nums text-red-400"
                }
              >
                {up ? "▲" : "▼"} {Math.abs(q.change).toFixed(2)} (
                {q.change_pct?.toFixed(2)}%)
              </span>
            </span>
          )
        })}
        <span className="ml-auto hidden shrink-0 text-[10px] uppercase tracking-widest text-slate-400 sm:inline">
          NSE · delayed quotes
        </span>
      </div>
    </div>
  )
}
