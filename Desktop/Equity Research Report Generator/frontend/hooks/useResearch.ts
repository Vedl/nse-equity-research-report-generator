"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchResearch, normaliseTicker } from "@/lib/api"
import type { Research } from "@/lib/schemas"

export function useResearch(ticker: string) {
  const normTicker = normaliseTicker(ticker)
  return useQuery<Research, Error>({
    queryKey: ["research", normTicker],
    queryFn: () => fetchResearch(normTicker),
    staleTime: 10 * 60 * 1000, // 10 min — matches backend TTL cache
  })
}
