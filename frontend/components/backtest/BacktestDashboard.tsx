"use client"

import { BacktestResult, FactorResult } from "@/lib/backtest-schema"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { fmtPct, fmtMultiple } from "@/lib/formatters"
import dynamic from "next/dynamic"

// Dynamically import Recharts to avoid SSR issues
const FactorChart = dynamic(() => import("./FactorChart"), { ssr: false })

export function BacktestDashboard({ data }: { data: BacktestResult }) {
  return (
    <div className="space-y-8">
      {/* Overview Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Universe Size</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.universe_size}</div>
            <p className="text-xs text-muted-foreground mt-1">Nifty 500 Equities</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Backtest Horizon</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.backtest_start.split('-')[0]} - {data.backtest_end.split('-')[0]}</div>
            <p className="text-xs text-muted-foreground mt-1">Monthly rebalanced</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Benchmark</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">Nifty 50</div>
            <p className="text-xs text-muted-foreground mt-1">Total Return Index</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Rebalance Frequency</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">Monthly</div>
            <p className="text-xs text-muted-foreground mt-1">No transaction costs assumed</p>
          </CardContent>
        </Card>
      </div>

      {/* Factor Cards */}
      <div className="space-y-6">
        {data.factors.map((factor, i) => (
          <FactorCard key={i} factor={factor} />
        ))}
      </div>

      {/* Methodology Notes */}
      <Card className="bg-muted/30">
        <CardHeader>
          <CardTitle className="text-lg">Methodology & Disclosures</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <div>
            <span className="font-semibold text-foreground">Caveats:</span>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              {data.caveats.map((caveat, i) => (
                <li key={i}>{caveat}</li>
              ))}
            </ul>
          </div>
          <div>
            <span className="font-semibold text-foreground">Methodology:</span>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              {data.methodology_notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function FactorCard({ factor }: { factor: FactorResult }) {
  return (
    <Card className="overflow-hidden border-border/60">
      <CardHeader className="bg-muted/30 border-b border-border/40">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-xl">{factor.factor_name}</CardTitle>
            <CardDescription className="mt-1">
              Long: {factor.long_label} | Short: {factor.short_label}
            </CardDescription>
          </div>
          <div className="text-right">
            <div className="text-sm font-medium">Spread CAGR</div>
            <div className={`text-xl font-bold ${factor.spread_cagr >= 0 ? "text-emerald-500" : "text-red-500"}`}>
              {factor.spread_cagr >= 0 ? "+" : ""}{fmtPct(factor.spread_cagr)}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="grid lg:grid-cols-4 divide-y lg:divide-y-0 lg:divide-x border-border/40">
          
          {/* Chart Section */}
          <div className="lg:col-span-3 p-6">
            <h4 className="text-sm font-semibold mb-4 text-muted-foreground">Cumulative Returns (Log Scale)</h4>
            <div className="h-[350px] w-full">
              <FactorChart factor={factor} />
            </div>
          </div>
          
          {/* Stats Section */}
          <div className="p-6 bg-muted/10 space-y-6">
            <div>
              <h4 className="text-sm font-semibold mb-3 border-b pb-1">Performance (CAGR)</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Long Portfolio:</span>
                  <span className="font-medium text-emerald-500">{fmtPct(factor.long_cagr)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Short Portfolio:</span>
                  <span className="font-medium text-red-500">{fmtPct(factor.short_cagr)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Benchmark:</span>
                  <span className="font-medium">{fmtPct(factor.benchmark_cagr)}</span>
                </div>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-3 border-b pb-1">Risk & Reliability</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Spread Sharpe:</span>
                  <span className="font-medium">{fmtMultiple(factor.spread_sharpe)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Hit Rate (Years &gt; 0):</span>
                  <span className="font-medium">{fmtPct(factor.hit_rate)}</span>
                </div>
                {factor.ic_mean !== null && factor.ic_mean !== undefined && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Rank IC (Mean):</span>
                    <span className="font-medium">{factor.ic_mean.toFixed(3)}</span>
                  </div>
                )}
              </div>
            </div>
            
            <div>
              <h4 className="text-sm font-semibold mb-3 border-b pb-1">Max Drawdown</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Long Portfolio:</span>
                  <span className="font-medium text-red-500">{fmtPct(factor.max_drawdown_long)}</span>
                </div>
              </div>
            </div>

          </div>
        </div>
      </CardContent>
    </Card>
  )
}
