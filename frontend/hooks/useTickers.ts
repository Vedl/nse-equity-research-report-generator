"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchTickers } from "@/lib/api"
import type { TickerItem } from "@/lib/schemas"

export function useTickers() {
  return useQuery<TickerItem[], Error>({
    queryKey: ["tickers"],
    queryFn: fetchTickers,
    staleTime: 60 * 60 * 1000, // 1 hr — ticker list changes rarely
  })
}
