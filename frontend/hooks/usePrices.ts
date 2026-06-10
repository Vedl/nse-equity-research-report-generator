"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchPrices, normaliseTicker } from "@/lib/api"
import type { PriceBar } from "@/lib/schemas"

export function usePrices(ticker: string, period = "1y") {
  const normTicker = normaliseTicker(ticker)
  return useQuery<PriceBar[], Error>({
    queryKey: ["prices", normTicker, period],
    queryFn: () => fetchPrices(normTicker, period),
    staleTime: 5 * 60 * 1000, // 5 min — price history is more time-sensitive
  })
}
