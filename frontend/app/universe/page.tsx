"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

interface UniverseEntry {
  ticker: string
  name: string | null
  sector: string | null
  industry: string | null
  valuation_family: string
  primary_model: string
  data_status: "complete" | "partial" | "unknown"
  has_report: boolean
}

async function fetchUniverse(): Promise<UniverseEntry[]> {
  const res = await fetch("/api/universe")
  if (!res.ok) throw new Error(`Universe fetch failed (${res.status})`)
  return res.json()
}

const FAMILY_LABELS: Record<string, string> = {
  BANKS_NBFCS: "Banks / NBFCs",
  INSURANCE: "Insurance",
  UTILITIES_PSU: "Utilities / PSU",
  REAL_ESTATE: "Real Estate",
  METALS_MINING: "Metals & Mining",
  CONGLOMERATES: "Conglomerates",
  PHARMA: "Pharma",
  IT_TECH: "IT / Tech",
  CONSUMER_FMCG: "Consumer / FMCG",
  OIL_GAS: "Oil & Gas",
  DEFAULT: "General (DCF)",
}

const STATUS_STYLE: Record<string, string> = {
  complete: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  partial: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  unknown: "bg-slate-500/15 text-slate-400 border-slate-500/30",
}

export default function UniversePage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["universe"],
    queryFn: fetchUniverse,
    staleTime: 10 * 60_000,
  })

  const [search, setSearch] = useState("")
  const [sector, setSector] = useState<string>("all")
  const [family, setFamily] = useState<string>("all")

  const sectors = useMemo(
    () =>
      Array.from(new Set((data ?? []).map((e) => e.sector).filter(Boolean))).sort() as string[],
    [data]
  )

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim()
    return (data ?? []).filter((e) => {
      if (sector !== "all" && e.sector !== sector) return false
      if (family !== "all" && e.valuation_family !== family) return false
      if (!q) return true
      return (
        e.ticker.toLowerCase().includes(q) ||
        (e.name ?? "").toLowerCase().includes(q)
      )
    })
  }, [data, search, sector, family])

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6">
      <div className="mb-2 flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Company Universe</h1>
        <span className="font-mono text-xs text-muted-foreground">
          {filtered.length} / {data?.length ?? 0} companies
        </span>
      </div>
      <p className="mb-6 text-sm text-muted-foreground">
        All Nifty 500 constituents with their rule-based valuation family. Data
        status reflects what the engine has cached — complete (financials),
        partial (profile only), or unknown (not yet fetched).
      </p>

      {/* Filter bar */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <Input
          placeholder="Search ticker or company name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:max-w-xs"
        />
        <Select value={sector} onValueChange={(v) => setSector(v ?? "all")}>
          <SelectTrigger className="sm:w-56">
            <SelectValue placeholder="Sector" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All sectors</SelectItem>
            {sectors.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={family} onValueChange={(v) => setFamily(v ?? "all")}>
          <SelectTrigger className="sm:w-56">
            <SelectValue placeholder="Valuation family" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All valuation families</SelectItem>
            {Object.entries(FAMILY_LABELS).map(([k, v]) => (
              <SelectItem key={k} value={k}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading && (
        <p className="py-12 text-center text-sm text-muted-foreground">
          Loading universe…
        </p>
      )}
      {error instanceof Error && (
        <p className="py-12 text-center text-sm text-destructive">
          {error.message}
        </p>
      )}

      {data && (
        <div className="overflow-x-auto rounded-md border border-border/40">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Company</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead>Valuation family</TableHead>
                <TableHead>Data status</TableHead>
                <TableHead>Report</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.slice(0, 600).map((e) => (
                <TableRow key={e.ticker}>
                  <TableCell>
                    <Link
                      href={`/research/${e.ticker}`}
                      className="font-mono text-sm text-sky-500 hover:underline"
                    >
                      {e.ticker}
                    </Link>
                  </TableCell>
                  <TableCell className="max-w-[260px] truncate text-sm">
                    {e.name}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {e.sector ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="font-normal">
                      {FAMILY_LABELS[e.valuation_family] ?? e.valuation_family}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={STATUS_STYLE[e.data_status]}
                    >
                      {e.data_status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">
                    {e.has_report ? (
                      <span className="text-emerald-400">generated</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
