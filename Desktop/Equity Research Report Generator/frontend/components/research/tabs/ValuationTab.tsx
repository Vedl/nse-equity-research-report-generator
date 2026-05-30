"use client"

import { useState, useMemo } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Slider } from "@/components/ui/slider"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { fmtINR, fmtPct, fmtMultiple } from "@/lib/formatters"
import { recalculateDCF, calcUpside } from "@/lib/dcf"
import type { Research } from "@/lib/schemas"
import { cn } from "@/lib/utils"

interface Props { data: Research }

// ── Sensitivity heatmap ───────────────────────────────────────────────────

function SensitivityHeatmap({ dcf, currentPrice }: {
  dcf: NonNullable<Research["valuation"]["dcf"]>
  currentPrice: number | null
}) {
  const { sensitivity, sensitivity_wacc_labels, sensitivity_tg_labels, assumptions } = dcf
  if (!sensitivity?.length) return null

  const waccLabels = sensitivity_wacc_labels ?? []
  const tgLabels = sensitivity_tg_labels ?? []
  const baseWacc = assumptions.wacc
  const baseTG = assumptions.terminal_growth

  // Color scale: red (< current) → white → green (> current)
  function cellColor(value: number | null) {
    if (value == null || currentPrice == null) return "bg-muted/40"
    const ratio = value / currentPrice
    if (ratio >= 2.0) return "bg-emerald-600/70 text-white"
    if (ratio >= 1.5) return "bg-emerald-500/60 text-white"
    if (ratio >= 1.2) return "bg-emerald-400/50"
    if (ratio >= 1.05) return "bg-emerald-300/40"
    if (ratio >= 0.95) return "bg-muted/30"
    if (ratio >= 0.8) return "bg-red-300/40"
    if (ratio >= 0.6) return "bg-red-400/50"
    return "bg-red-500/60 text-white"
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="p-1 text-left text-muted-foreground font-normal">
              WACC ↓ / TG →
            </th>
            {tgLabels.map((tg) => (
              <th key={tg} className="p-1 text-center tabular-nums font-medium">
                {fmtPct(tg, 1)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sensitivity.map((row, ri) => {
            const isBaseWacc = waccLabels[ri] != null &&
              Math.abs((waccLabels[ri] ?? 0) - (baseWacc ?? 0)) < 0.001
            return (
              <tr key={ri}>
                <td className={cn(
                  "p-1 tabular-nums font-medium",
                  isBaseWacc && "text-sky-400"
                )}>
                  {waccLabels[ri] != null ? fmtPct(waccLabels[ri]!, 2) : `Row ${ri + 1}`}
                </td>
                {row.map((cell, ci) => {
                  const isBaseTG = tgLabels[ci] != null &&
                    Math.abs((tgLabels[ci] ?? 0) - (baseTG ?? 0)) < 0.001
                  const isBase = isBaseWacc && isBaseTG
                  return (
                    <td key={ci} className={cn(
                      "p-1 text-center tabular-nums rounded transition-colors",
                      cellColor(cell),
                      isBase && "ring-2 ring-sky-500 ring-inset font-bold"
                    )}>
                      {cell != null ? fmtINR(cell) : "—"}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted-foreground">
        Base case (sky border): WACC {fmtPct(baseWacc, 2)}, TG {fmtPct(baseTG, 2)}.
        Green = above current price; red = below.
      </p>
    </div>
  )
}

// ── Comps table ───────────────────────────────────────────────────────────

type SortKey = "pe" | "ev_ebitda" | "pb" | "ev_sales"

function CompsTable({ comps, targetTicker }: {
  comps: Research["valuation"]["comps"]
  targetTicker: string
}) {
  const [sortKey, setSortKey] = useState<SortKey>("pe")
  const [sortAsc, setSortAsc] = useState(true)

  const sorted = useMemo(() => {
    return [...comps].sort((a, b) => {
      const av = a[sortKey] ?? Infinity
      const bv = b[sortKey] ?? Infinity
      return sortAsc ? av - bv : bv - av
    })
  }, [comps, sortKey, sortAsc])

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortAsc((prev) => !prev)
    else { setSortKey(key); setSortAsc(true) }
  }

  function SortHeader({ k, label }: { k: SortKey; label: string }) {
    const active = sortKey === k
    return (
      <TableHead
        className="cursor-pointer select-none text-right hover:text-foreground"
        onClick={() => handleSort(k)}
      >
        {label}
        {active && <span className="ml-1">{sortAsc ? "↑" : "↓"}</span>}
      </TableHead>
    )
  }

  if (!comps.length) return (
    <p className="text-sm text-muted-foreground py-4">No comparable company data available.</p>
  )

  return (
    <ScrollArea>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Company</TableHead>
            <SortHeader k="pe" label="P/E" />
            <SortHeader k="ev_ebitda" label="EV/EBITDA" />
            <SortHeader k="pb" label="P/B" />
            <SortHeader k="ev_sales" label="EV/Sales" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((peer) => {
            const isTarget = peer.ticker.toUpperCase() === targetTicker.toUpperCase()
            return (
              <TableRow
                key={peer.ticker}
                className={cn(isTarget && "bg-sky-500/5 font-semibold")}
              >
                <TableCell>
                  <div>
                    <span className="font-mono text-sm">
                      {peer.ticker.replace(".NS", "")}
                    </span>
                    <span className="ml-2 text-xs text-muted-foreground">{peer.name}</span>
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">{fmtMultiple(peer.pe)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtMultiple(peer.ev_ebitda)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtMultiple(peer.pb)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtMultiple(peer.ev_sales)}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────

export function ValuationTab({ data }: Props) {
  const { valuation, price, company } = data
  const dcf = valuation.dcf
  const currentPrice = price.current

  // Slider state — initialised from API assumptions
  const [wacc, setWacc] = useState(
    dcf?.assumptions.wacc != null ? Math.round(dcf.assumptions.wacc * 1000) / 10 : 10
  )
  const [tg, setTg] = useState(
    dcf?.assumptions.terminal_growth != null
      ? Math.round(dcf.assumptions.terminal_growth * 1000) / 10
      : 4
  )
  const [horizon, setHorizon] = useState(
    dcf?.assumptions.projection_years ?? 5
  )

  // Client-side DCF recalculation
  const liveIntrinsic = useMemo(() => {
    if (!dcf?.base_fcff || !dcf.shares_outstanding) return null
    return recalculateDCF(
      dcf.base_fcff,
      dcf.growth_rate ?? 0.08,
      wacc / 100,
      tg / 100,
      horizon,
      dcf.net_debt ?? 0,
      dcf.shares_outstanding
    )
  }, [dcf, wacc, tg, horizon])

  const liveUpside = calcUpside(liveIntrinsic, currentPrice)

  return (
    <div className="space-y-6">
      {/* Interactive DCF */}
      {dcf && (
        <Card className={cn(
          "border-border/40",
          dcf.diverges_materially && "border-amber-500/20"
        )}>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Interactive DCF — Adjust Assumptions
              </CardTitle>
              {dcf.diverges_materially && (
                <span className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400">
                  Methodological note
                </span>
              )}
            </div>
            {dcf.diverges_materially && (
              <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                FCFF DCF is sensitive to capex assumptions and may understate
                capital-intensive or high-growth companies whose trailing free
                cash flow does not yet reflect future earnings power. The
                sensitivity table below shows the range of outcomes under
                different assumptions — see the appendix for full details.
              </p>
            )}
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-6 sm:grid-cols-3">
              {/* WACC Slider */}
              <div>
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">WACC</span>
                  <span className="tabular-nums font-medium text-sky-400">{wacc.toFixed(1)}%</span>
                </div>
                <Slider
                  min={8} max={16} step={0.1}
                  value={[wacc]}
                  onValueChange={(vals) => setWacc(Array.isArray(vals) ? vals[0] : vals)}
                  className="cursor-pointer"
                />
                <div className="mt-1 flex justify-between text-[10px] text-muted-foreground/60">
                  <span>8%</span><span>16%</span>
                </div>
              </div>

              {/* Terminal Growth Slider */}
              <div>
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Terminal Growth</span>
                  <span className="tabular-nums font-medium text-sky-400">{tg.toFixed(1)}%</span>
                </div>
                <Slider
                  min={2} max={6} step={0.1}
                  value={[tg]}
                  onValueChange={(vals) => setTg(Array.isArray(vals) ? vals[0] : vals)}
                  className="cursor-pointer"
                />
                <div className="mt-1 flex justify-between text-[10px] text-muted-foreground/60">
                  <span>2%</span><span>6%</span>
                </div>
              </div>

              {/* Horizon Slider */}
              <div>
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Projection Horizon</span>
                  <span className="tabular-nums font-medium text-sky-400">{horizon}Y</span>
                </div>
                <Slider
                  min={3} max={7} step={1}
                  value={[horizon]}
                  onValueChange={(vals) => setHorizon(Array.isArray(vals) ? vals[0] : vals)}
                  className="cursor-pointer"
                />
                <div className="mt-1 flex justify-between text-[10px] text-muted-foreground/60">
                  <span>3Y</span><span>7Y</span>
                </div>
              </div>
            </div>

            {/* Live result */}
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">Live Intrinsic Value</p>
                <p className="tabular-nums text-2xl font-bold">
                  {liveIntrinsic != null ? fmtINR(liveIntrinsic) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  liveUpside == null ? "text-muted-foreground"
                    : liveUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {liveUpside != null
                    ? `${liveUpside >= 0 ? "+" : ""}${fmtPct(liveUpside)}`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Backend DCF (Base Case)</p>
                <p className="tabular-nums text-2xl font-bold text-muted-foreground">
                  {dcf.intrinsic_value != null ? fmtINR(dcf.intrinsic_value) : "—"}
                </p>
              </div>
            </div>

            {/* Sensitivity heatmap */}
            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Sensitivity — Intrinsic Value / Share
              </p>
              <SensitivityHeatmap dcf={dcf} currentPrice={currentPrice} />
            </div>

            {/* Assumptions */}
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="text-xs">
                Rf {fmtPct(dcf.assumptions.risk_free_rate, 1)}
              </Badge>
              <Badge variant="outline" className="text-xs">
                ERP {fmtPct(dcf.assumptions.erp, 1)}
              </Badge>
              <Badge variant="outline" className="text-xs">
                Growth {fmtPct(dcf.growth_rate, 1)}
              </Badge>
              <Badge variant="outline" className="text-xs text-amber-400 border-amber-500/30">
                Not investment advice — illustrative only
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Comparable companies */}
      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">
            Comparable Companies
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-4">
          <CompsTable comps={valuation.comps} targetTicker={company.ticker} />
        </CardContent>
      </Card>
    </div>
  )
}
