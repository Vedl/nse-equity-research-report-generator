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
  const ri = valuation.residual_income
  const er = valuation.excess_return
  const fin = valuation.financial
  const sotp = valuation.sotp
  const breakeven = valuation.path_to_breakeven
  const rel = valuation.relative
  const modelUsed = valuation.model_used
  const currentPrice = price.current
  const intrinsicValue = valuation.intrinsic_value ?? null

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

  // Upside calculation for other models
  const riUpside = ri ? calcUpside(ri.intrinsic_value, currentPrice) : null
  const erUpside = er ? calcUpside(er.intrinsic_value, currentPrice) : null
  const finUpside = fin ? calcUpside(fin.intrinsic_value, currentPrice) : null
  const sotpUpside = sotp ? calcUpside(sotp.intrinsic_value, currentPrice) : null
  const evEbitdaUpside = modelUsed === "ev_ebitda" || modelUsed === "ev_sales" ? calcUpside(intrinsicValue, currentPrice) : null

  return (
    <div className="space-y-6">
      {/* Routed Model Details */}
      {modelUsed === "fcff" && dcf && (
        <Card className={cn(
          "border-border/40",
          dcf.diverges_materially && "border-amber-500/20"
        )}>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Interactive DCF — Adjust Assumptions
              </CardTitle>
              <span className="shrink-0 rounded-full bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 text-[10px] font-medium text-sky-400">
                Routed Model
              </span>
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

      {modelUsed === "ri" && ri && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Residual Income (RI) Valuation
              </CardTitle>
              <span className="shrink-0 rounded-full bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 text-[10px] font-medium text-indigo-400">
                Routed Model
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              This company was routed to the Residual Income model because its trailing free cash flows are volatile or negative, but it has a solid book value and positive earnings.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">RI Intrinsic Value</p>
                <p className="tabular-nums text-2xl font-bold">
                  {ri.intrinsic_value != null ? fmtINR(ri.intrinsic_value) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  riUpside == null ? "text-muted-foreground"
                    : riUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {riUpside != null
                    ? `${riUpside >= 0 ? "+" : ""}${fmtPct(riUpside)}`
                    : "—"}
                </p>
              </div>
            </div>

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Assumptions & Inputs
              </p>
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Book Value / Share</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtINR(ri.book_value_per_share)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Cost of Equity (Ke)</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(ri.cost_of_equity, 2)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Growth Rate</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(ri.growth_rate, 2)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Terminal Growth</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(ri.terminal_growth, 2)}</p>
                </div>
              </div>
            </div>

            <div className="text-xs text-muted-foreground leading-relaxed bg-muted/10 p-3 rounded border border-border/20">
              <strong>Methodology:</strong> Intrinsic Value = Book Value + Σ PV(Net Income − Ke × Book Value_t-1) + PV(Terminal Residual Income). Net income is projected to grow at {fmtPct(ri.growth_rate, 1)} over the projection horizon.
            </div>
          </CardContent>
        </Card>
      )}

      {modelUsed === "excess_return" && er && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Excess Return Valuation (Financial Sector)
              </CardTitle>
              <span className="shrink-0 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                Routed Model
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Routed to the Excess Return model suitable for banks and financials. Since financial institutions&apos; primary input is money/debt (deposits), standard free cash flow models do not apply.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">Excess Return Intrinsic Value</p>
                <p className="tabular-nums text-2xl font-bold">
                  {er.intrinsic_value != null ? fmtINR(er.intrinsic_value) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  erUpside == null ? "text-muted-foreground"
                    : erUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {erUpside != null
                    ? `${erUpside >= 0 ? "+" : ""}${fmtPct(erUpside)}`
                    : "—"}
                </p>
              </div>
              {er.is_pb_fallback && (
                <div className="flex items-center">
                  <span className="text-xs font-semibold px-2 py-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    P/B Multiple Fallback
                  </span>
                </div>
              )}
            </div>

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Assumptions & Inputs
              </p>
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Book Value / Share</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtINR(er.book_value_per_share)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Cost of Equity (Ke)</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(er.cost_of_equity, 2)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Average ROE</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(er.roe, 2)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Sustainable Growth</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(er.sustainable_growth, 2)}</p>
                </div>
              </div>
            </div>

            <div className="text-xs text-muted-foreground leading-relaxed bg-muted/10 p-3 rounded border border-border/20">
              <strong>Methodology:</strong> Intrinsic Value = Book Value + Σ PV((ROE − Ke) × Book Value_t-1) + PV(Terminal Value). Book value is projected to grow at the sustainable growth rate of {fmtPct(er.sustainable_growth, 1)} (ROE × Retention Ratio).
            </div>
          </CardContent>
        </Card>
      )}

      {modelUsed === "ev_ebitda" && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                EV/EBITDA Relative Valuation (High-Capex Fallback)
              </CardTitle>
              <span className="shrink-0 rounded-full bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-400">
                Routed Model
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Routed to relative EV/EBITDA valuation because this company is in a highly intensive capex cycle with leveraged capital structures and negative free cash flow. Traditional DCF cash flow projections would be highly speculative.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">Implied Price (Comps Median)</p>
                <p className="tabular-nums text-2xl font-bold">
                  {intrinsicValue != null ? fmtINR(intrinsicValue) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  evEbitdaUpside == null ? "text-muted-foreground"
                    : evEbitdaUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {evEbitdaUpside != null
                    ? `${evEbitdaUpside >= 0 ? "+" : ""}${fmtPct(evEbitdaUpside)}`
                    : "—"}
                </p>
              </div>
            </div>

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Implied Valuation Multiples
              </p>
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Implied EV/EBITDA Price</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    {rel?.implied_ev_ebitda != null ? fmtINR(rel.implied_ev_ebitda) : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Implied P/E Price</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    {rel?.implied_pe != null ? fmtINR(rel.implied_pe) : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Implied P/B Price</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    {rel?.implied_pb != null ? fmtINR(rel.implied_pb) : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Implied EV/Sales Price</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    {rel?.implied_ev_sales != null ? fmtINR(rel.implied_ev_sales) : "—"}
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {modelUsed === "sotp" && sotp && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Sum-of-the-Parts (SOTP) Valuation
              </CardTitle>
              <span className="shrink-0 rounded-full bg-fuchsia-500/10 border border-fuchsia-500/20 px-2 py-0.5 text-[10px] font-medium text-fuchsia-400">
                Routed Model
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Routed to SOTP model because this company operates as a conglomerate with distinct segments that command different market multiples.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">SOTP Intrinsic Value</p>
                <p className="tabular-nums text-2xl font-bold">
                  {sotp.intrinsic_value != null ? fmtINR(sotp.intrinsic_value) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  sotpUpside == null ? "text-muted-foreground"
                    : sotpUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {sotpUpside != null
                    ? `${sotpUpside >= 0 ? "+" : ""}${fmtPct(sotpUpside)}`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Implied Blended EV/EBITDA</p>
                <p className="tabular-nums text-2xl font-bold text-muted-foreground">
                  {sotp.blended_ev_ebitda != null ? `${sotp.blended_ev_ebitda.toFixed(1)}x` : "—"}
                </p>
              </div>
            </div>

            {sotp.is_fallback && (
              <div className="text-xs text-amber-500 bg-amber-500/10 p-3 rounded border border-amber-500/20">
                <strong>Fallback Note:</strong> {sotp.fallback_note}
              </div>
            )}

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Segment Breakdown
              </p>
              <ScrollArea>
                <Table className="text-xs">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Segment</TableHead>
                      <TableHead className="text-right">EBITDA Share</TableHead>
                      <TableHead className="text-right">Assigned Multiple</TableHead>
                      <TableHead className="text-right">Implied EV</TableHead>
                      <TableHead>Analyst Note</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sotp.segments.map((seg, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-medium">{seg.name}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtPct(seg.ebitda_share)}</TableCell>
                        <TableCell className="text-right tabular-nums">{seg.ev_ebitda_multiple != null ? `${seg.ev_ebitda_multiple.toFixed(1)}x` : "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{seg.segment_ev != null ? fmtINR(seg.segment_ev) : "—"}</TableCell>
                        <TableCell className="text-muted-foreground truncate max-w-[200px]" title={seg.note}>{seg.note}</TableCell>
                      </TableRow>
                    ))}
                    <TableRow className="bg-muted/10 font-bold">
                      <TableCell>Total</TableCell>
                      <TableCell className="text-right tabular-nums">100%</TableCell>
                      <TableCell className="text-right tabular-nums">—</TableCell>
                      <TableCell className="text-right tabular-nums">{sotp.total_ev != null ? fmtINR(sotp.total_ev) : "—"}</TableCell>
                      <TableCell></TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
                <ScrollBar orientation="horizontal" />
              </ScrollArea>
              
              <div className="mt-4 grid gap-4 grid-cols-2">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Less: Net Debt</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums text-red-400">
                    {sotp.net_debt != null ? `-${fmtINR(sotp.net_debt)}` : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Implied Equity Value</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums text-emerald-400">
                    {sotp.equity_value != null ? fmtINR(sotp.equity_value) : "—"}
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {modelUsed === "financial" && fin && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Justified P/B (Financial Sector)
              </CardTitle>
              <span className="shrink-0 rounded-full bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 text-[10px] font-medium text-blue-400">
                Routed Model
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Routed to the Justified Price-to-Book model (P/B = (ROE - g) / (Ke - g)). For banks and NBFCs, book value is the primary driver of value, and the premium commanded over book value depends directly on the ROE spread over the cost of equity.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">Financial Intrinsic Value</p>
                <p className="tabular-nums text-2xl font-bold">
                  {fin.intrinsic_value != null ? fmtINR(fin.intrinsic_value) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  finUpside == null ? "text-muted-foreground"
                    : finUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {finUpside != null
                    ? `${finUpside >= 0 ? "+" : ""}${fmtPct(finUpside)}`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Target Justified P/B</p>
                <p className="tabular-nums text-2xl font-bold text-muted-foreground">
                  {fin.justified_pb != null ? `${fin.justified_pb.toFixed(2)}x` : "—"}
                </p>
              </div>
            </div>

            {fin.is_fallback && (
              <div className="text-xs text-amber-500 bg-amber-500/10 p-3 rounded border border-amber-500/20">
                <strong>Fallback Note:</strong> {fin.fallback_note}
              </div>
            )}

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Assumptions & Drivers
              </p>
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Return on Equity (ROE)</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(fin.roe, 2)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Cost of Equity (Ke)</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(fin.cost_of_equity, 2)}</p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">ROE Spread (ROE - Ke)</p>
                  <p className={cn(
                    "mt-1 text-sm font-semibold tabular-nums",
                    (fin.roe_ke_spread ?? 0) > 0 ? "text-emerald-400" : "text-red-400"
                  )}>
                    {fin.roe_ke_spread != null ? `${fin.roe_ke_spread > 0 ? "+" : ""}${fmtPct(fin.roe_ke_spread, 2)}` : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Terminal Growth (g)</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{fmtPct(fin.growth_rate, 2)}</p>
                </div>
              </div>
            </div>

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Justified P/B Sensitivity
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="p-1 text-left text-muted-foreground font-normal">Ke ↓ / ROE →</th>
                      {fin.sensitivity_roe_labels.map((r, i) => (
                        <th key={i} className="p-1 text-center tabular-nums font-medium">{fmtPct(r, 1)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {fin.sensitivity_pb.map((row, ri) => (
                      <tr key={ri}>
                        <td className="p-1 tabular-nums font-medium">
                          {fmtPct(fin.sensitivity_ke_labels[ri], 1)}
                        </td>
                        {row.map((val, ci) => (
                          <td key={ci} className={cn(
                            "p-1 text-center tabular-nums rounded",
                            val != null && fin.justified_pb != null && Math.abs(val - fin.justified_pb) < 0.01
                              ? "bg-sky-500/30 ring-1 ring-sky-500 text-sky-50 font-bold"
                              : "bg-muted/30"
                          )}>
                            {val != null ? `${val.toFixed(2)}x` : "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {modelUsed === "ev_sales" && breakeven && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                Startup Valuation (EV/Sales + Path to Breakeven)
              </CardTitle>
              <span className="shrink-0 rounded-full bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 text-[10px] font-medium text-rose-400">
                Routed Model
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Routed to EV/Sales because this company has negative EBITDA (loss-making). Valuation relies on revenue multiples, alongside an analysis of cash runway and the gap to operating breakeven.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/30 p-4">
              <div>
                <p className="text-xs text-muted-foreground">Implied EV/Sales Target</p>
                <p className="tabular-nums text-2xl font-bold">
                  {intrinsicValue != null ? fmtINR(intrinsicValue) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  evEbitdaUpside == null ? "text-muted-foreground"
                    : evEbitdaUpside >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {evEbitdaUpside != null
                    ? `${evEbitdaUpside >= 0 ? "+" : ""}${fmtPct(evEbitdaUpside)}`
                    : "—"}
                </p>
              </div>
            </div>

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Path to Profitability Metrics
              </p>
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Cash Runway (Quarters)</p>
                  <p className={cn(
                    "mt-1 text-sm font-semibold tabular-nums",
                    (breakeven.cash_runway_quarters ?? 0) < 4 ? "text-red-400" : "text-foreground"
                  )}>
                    {breakeven.cash_runway_quarters != null ? `${breakeven.cash_runway_quarters.toFixed(1)} Qtrs` : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Breakeven Revenue Req.</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    {breakeven.breakeven_revenue != null ? fmtINR(breakeven.breakeven_revenue) : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Gap to Breakeven</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums text-rose-400">
                    {breakeven.gap_to_breakeven_pct != null ? `+${fmtPct(breakeven.gap_to_breakeven_pct, 1)} Rev` : "—"}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Gross Margin</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    {breakeven.gross_margin != null ? fmtPct(breakeven.gross_margin, 1) : "—"}
                  </p>
                </div>
              </div>
            </div>
            
            <div className="text-xs text-muted-foreground leading-relaxed bg-muted/10 p-3 rounded border border-border/20">
              <strong>Analysis:</strong> For a pre-profit company, cash runway dictates survival risk. The &quot;Gap to Breakeven&quot; indicates how much current revenue needs to grow (holding gross margins constant and assuming fixed operating costs) to reach zero EBITDA.
            </div>
          </CardContent>
        </Card>
      )}

      {/* India Valuation Engine */}
      {valuation.india && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <CardTitle className="text-sm font-medium">
                India Valuation Engine (Proprietary)
              </CardTitle>
              <span className="shrink-0 rounded-full bg-purple-500/10 border border-purple-500/20 px-2 py-0.5 text-[10px] font-medium text-purple-400">
                Layered Adjustments
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              India-specific structural factors layered on top of traditional valuation models. Adjusts for PSU capital allocation risk, promoter quality, holding company discounts, and accruals-based earnings quality.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-purple-500/5 p-4 border border-purple-500/10">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Blended Valuation Target</p>
                <p className="tabular-nums text-2xl font-bold text-purple-400 mt-1">
                  {fmtINR(valuation.india.blended_value)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold mt-1",
                  valuation.india.blended_upside_pct >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {valuation.india.blended_upside_pct >= 0 ? "+" : ""}{fmtPct(valuation.india.blended_upside_pct)}
                </p>
              </div>
            </div>

            <div>
              <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Scoring & Adjustments
              </p>
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">PSU Status</p>
                  <p className="mt-1 text-sm font-semibold">
                    {valuation.india.is_psu ? (
                      <span className="text-red-400">Yes (-{fmtPct(valuation.india.psu_discount_pct, 1)})</span>
                    ) : (
                      "No (Private)"
                    )}
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Promoter Quality</p>
                  <p className={cn(
                    "mt-1 text-sm font-semibold tabular-nums",
                    valuation.india.promoter_score >= 80 ? "text-emerald-400" : valuation.india.promoter_score < 40 ? "text-red-400" : "text-foreground"
                  )}>
                    {valuation.india.promoter_score.toFixed(1)} / 100
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Earnings Quality</p>
                  <p className={cn(
                    "mt-1 text-sm font-semibold tabular-nums",
                    valuation.india.earnings_quality_score >= 80 ? "text-emerald-400" : valuation.india.earnings_quality_score < 40 ? "text-red-400" : "text-foreground"
                  )}>
                    {valuation.india.earnings_quality_score.toFixed(1)} / 100
                  </p>
                </div>
                <div className="rounded bg-muted/20 p-3">
                  <p className="text-[10px] text-muted-foreground">Primary Multiple</p>
                  <p className="mt-1 text-sm font-semibold">
                    {valuation.india.primary_multiple.replace("ev_", "EV/").toUpperCase()}
                  </p>
                </div>
              </div>
            </div>

            {(valuation.india.narrative_bullets.length > 0 || valuation.india.promoter_flags.length > 0 || valuation.india.earnings_quality_flags.length > 0) && (
              <div className="space-y-4 pt-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Analyst Notes
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {valuation.india.narrative_bullets.map((bullet, idx) => (
                    <li key={`nb-${idx}`} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-500/50" />
                      <span>{bullet}</span>
                    </li>
                  ))}
                  {valuation.india.promoter_flags.map((flag, idx) => (
                    <li key={`pf-${idx}`} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500/50" />
                      <span className="text-amber-500/90">{flag}</span>
                    </li>
                  ))}
                  {valuation.india.earnings_quality_flags.map((flag, idx) => (
                    <li key={`eqf-${idx}`} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-red-500/50" />
                      <span className="text-red-400">{flag}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Relative Valuation Cross-Check */}
      {rel && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              Relative Valuation Cross-Check (Peers Range)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 grid-cols-3">
              <div className="rounded bg-muted/10 p-3">
                <p className="text-[10px] text-muted-foreground">Comps Low</p>
                <p className="mt-1 text-sm font-semibold tabular-nums">{rel.low != null ? fmtINR(rel.low) : "—"}</p>
              </div>
              <div className="rounded bg-muted/10 p-3 border border-sky-500/20 bg-sky-500/5">
                <p className="text-[10px] text-sky-400 font-medium">Comps Median (Target)</p>
                <p className="mt-1 text-sm font-bold tabular-nums text-sky-400">{rel.median != null ? fmtINR(rel.median) : "—"}</p>
              </div>
              <div className="rounded bg-muted/10 p-3">
                <p className="text-[10px] text-muted-foreground">Comps High</p>
                <p className="mt-1 text-sm font-semibold tabular-nums">{rel.high != null ? fmtINR(rel.high) : "—"}</p>
              </div>
            </div>

            {/* Range visualization indicator */}
            {rel.low != null && rel.high != null && currentPrice != null && (
              <div className="pt-2">
                <div className="flex justify-between text-[10px] text-muted-foreground mb-1.5">
                  <span>Low: {fmtINR(rel.low)}</span>
                  <span className="font-semibold text-foreground">Current: {fmtINR(currentPrice)}</span>
                  <span>High: {fmtINR(rel.high)}</span>
                </div>
                <div className="relative h-2 rounded-full bg-muted overflow-hidden">
                  <div className="absolute h-full rounded-full bg-sky-500/20 left-[10%] right-[10%]" />
                  {(() => {
                    const minVal = Math.min(rel.low, currentPrice);
                    const maxVal = Math.max(rel.high, currentPrice);
                    const diff = maxVal - minVal;
                    const pct = diff > 0 ? ((currentPrice - minVal) / diff) * 100 : 50;
                    return (
                      <div
                        className="absolute h-4 w-4 rounded-full bg-sky-400 border-2 border-background -top-1 shadow"
                        style={{ left: `calc(${pct}% - 8px)` }}
                      />
                    );
                  })()}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* India Valuation Adjustments */}
      {valuation.india && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              India Valuation Adjustments (Proprietary Engine)
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Note: The intrinsic baseline valuation is adjusted for India-specific factors including PSU status, business group governance, promoter quality, and earnings quality.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-sky-500/5 p-4 border border-sky-500/20">
              <div>
                <p className="text-xs text-muted-foreground">Adjusted Intrinsic Value (Blended)</p>
                <p className="tabular-nums text-2xl font-bold text-sky-600 dark:text-sky-400">
                  {fmtINR(valuation.india.blended_value)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">vs Current Price</p>
                <p className={cn(
                  "tabular-nums text-2xl font-bold",
                  valuation.india.blended_upside_pct >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {valuation.india.blended_upside_pct >= 0 ? "+" : ""}
                  {fmtPct(valuation.india.blended_upside_pct)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Implied Revenue CAGR</p>
                <p className="tabular-nums text-2xl font-bold text-muted-foreground">
                  {fmtPct(valuation.india.implied_revenue_cagr)}
                </p>
              </div>
            </div>

            <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
              <div className="rounded bg-muted/20 p-3">
                <p className="text-[10px] text-muted-foreground">Sector Primary Multiple</p>
                <p className="mt-1 text-sm font-semibold">{valuation.india.primary_multiple}</p>
              </div>
              <div className="rounded bg-muted/20 p-3">
                <p className="text-[10px] text-muted-foreground">PSU Discount</p>
                <p className={cn(
                  "mt-1 text-sm font-semibold tabular-nums",
                  valuation.india.psu_discount_pct > 0 ? "text-red-500" : ""
                )}>
                  {valuation.india.psu_discount_pct > 0 ? `-${fmtPct(valuation.india.psu_discount_pct, 1)}` : "None"}
                </p>
              </div>
              <div className="rounded bg-muted/20 p-3">
                <p className="text-[10px] text-muted-foreground">Group / Holding Adjustment</p>
                <p className={cn(
                  "mt-1 text-sm font-semibold tabular-nums",
                  valuation.india.group_adjustment_pct > 0 ? "text-emerald-500" 
                    : valuation.india.group_adjustment_pct < 0 ? "text-red-500" : ""
                )}>
                  {valuation.india.group_adjustment_pct > 0 ? "+" : ""}
                  {fmtPct(valuation.india.group_adjustment_pct, 1)}
                </p>
              </div>
              <div className="rounded bg-muted/20 p-3">
                <p className="text-[10px] text-muted-foreground">Promoter Premium</p>
                <p className={cn(
                  "mt-1 text-sm font-semibold tabular-nums",
                  valuation.india.promoter_premium_pct > 0 ? "text-emerald-500"
                    : valuation.india.promoter_premium_pct < 0 ? "text-red-500" : ""
                )}>
                  {valuation.india.promoter_premium_pct > 0 ? "+" : ""}
                  {fmtPct(valuation.india.promoter_premium_pct, 1)}
                </p>
              </div>
            </div>

            {(valuation.india.narrative_bullets.length > 0 || valuation.india.promoter_flags.length > 0 || valuation.india.earnings_quality_flags.length > 0) && (
              <div>
                <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Analyst Notes & Flags
                </p>
                <ul className="space-y-1.5">
                  {valuation.india.narrative_bullets.map((n, i) => (
                    <li key={`note-${i}`} className="text-sm text-muted-foreground list-disc ml-5">
                      {n}
                    </li>
                  ))}
                  {valuation.india.promoter_flags.map((f, i) => (
                    <li key={`pf-${i}`} className="text-sm text-red-500 list-disc ml-5">
                      <span className="font-semibold text-red-600 dark:text-red-400">Governance Flag:</span> {f}
                    </li>
                  ))}
                  {valuation.india.earnings_quality_flags.map((f, i) => (
                    <li key={`eqf-${i}`} className="text-sm text-red-500 list-disc ml-5">
                      <span className="font-semibold text-red-600 dark:text-red-400">Earnings Quality Flag:</span> {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Broker Consensus */}
      {valuation.broker_target_price != null && (
        <Card className="border-border/40">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              Broker Consensus Target
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Based on {valuation.broker_analyst_count ?? "several"} analyst opinions. 
              Consensus recommendation: <span className="font-semibold uppercase">{valuation.broker_recommendation ?? "N/A"}</span>
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6 rounded-lg bg-muted/20 p-4 border border-border/50">
              <div>
                <p className="text-xs text-muted-foreground">Mean Target Price</p>
                <p className="tabular-nums text-2xl font-bold">
                  {fmtINR(valuation.broker_target_price)}
                </p>
              </div>
              {valuation.broker_upside_pct != null && (
                <div>
                  <p className="text-xs text-muted-foreground">Upside vs Current</p>
                  <p className={cn(
                    "tabular-nums text-2xl font-bold",
                    valuation.broker_upside_pct >= 0 ? "text-emerald-500" : "text-red-500"
                  )}>
                    {valuation.broker_upside_pct >= 0 ? "+" : ""}
                    {fmtPct(valuation.broker_upside_pct)}
                  </p>
                </div>
              )}
              {valuation.model_vs_broker_pct != null && (
                <div>
                  <p className="text-xs text-muted-foreground">Model Premium / (Discount)</p>
                  <p className={cn(
                    "tabular-nums text-2xl font-bold",
                    valuation.model_vs_broker_pct >= 0 ? "text-emerald-500" : "text-red-500"
                  )}>
                    {valuation.model_vs_broker_pct >= 0 ? "+" : ""}
                    {fmtPct(valuation.model_vs_broker_pct)}
                  </p>
                </div>
              )}
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
