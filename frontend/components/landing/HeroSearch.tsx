"use client"

import { useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { Search, Loader2 } from "lucide-react"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { useTickers } from "@/hooks/useTickers"
import { normaliseTicker } from "@/lib/api"

export function HeroSearch() {
  const router = useRouter()
  const { data: tickers, isLoading } = useTickers()
  const [query, setQuery] = useState("")

  const handleSelect = useCallback(
    (ticker: string) => {
      router.push(`/research/${normaliseTicker(ticker)}`)
    },
    [router]
  )

  const filtered = query.trim()
    ? (tickers ?? []).filter(
        (t) =>
          t.ticker.toLowerCase().includes(query.toLowerCase()) ||
          t.name.toLowerCase().includes(query.toLowerCase())
      ).slice(0, 12)
    : []

  return (
    <div className="w-full max-w-xl">
      <Command className="rounded-xl border border-border/60 bg-card shadow-lg">
        <div className="flex items-center border-b border-border/40 px-3">
          {isLoading ? (
            <Loader2 className="mr-2 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <CommandInput
            placeholder="Search ticker or company name…"
            value={query}
            onValueChange={setQuery}
            className="h-12 text-base border-0 focus:ring-0 bg-transparent"
          />
        </div>
        {query.trim() && (
          <CommandList className="max-h-64">
            {filtered.length === 0 && !isLoading && (
              <CommandEmpty className="py-6 text-sm text-muted-foreground">
                No results for &ldquo;{query}&rdquo;
              </CommandEmpty>
            )}
            {filtered.length > 0 && (
              <CommandGroup>
                {filtered.map((t) => (
                  <CommandItem
                    key={t.ticker}
                    value={t.ticker}
                    onSelect={() => handleSelect(t.ticker)}
                    className="flex items-center justify-between px-4 py-2.5 cursor-pointer"
                  >
                    <span className="font-mono text-sm font-medium">
                      {t.ticker.replace(".NS", "")}
                    </span>
                    <span className="ml-3 flex-1 truncate text-sm text-muted-foreground">
                      {t.name}
                    </span>
                    <span className="ml-2 text-xs text-muted-foreground/60">
                      {t.sector}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        )}
      </Command>
      <p className="mt-2 text-center text-xs text-muted-foreground">
        Try RELIANCE, HDFCBANK, TCS, INFY…
      </p>
    </div>
  )
}
