import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import dynamic from "next/dynamic"
import { RevenueMarginChart } from "@/components/charts/RevenueMarginChart"
import { fmtPct, fmtMultiple, fmtINR } from "@/lib/formatters"
import { calcUpside } from "@/lib/dcf"
import type { Research } from "@/lib/schemas"

// TradingView uses canvas — must be client-only (no SSR)
const PriceChart = dynamic(
  () => import("@/components/charts/PriceChart").then((m) => m.PriceChart),
  { ssr: false, loading: () => <div className="h-64 animate-pulse rounded-lg bg-muted" /> }
)

interface Props {
  data: Research
  ticker: string
}

function RatioItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="tabular-nums text-sm font-semibold">{value}</span>
    </div>
  )
}

export function OverviewTab({ data, ticker }: Props) {
  const { ratios, valuation, price, company } = data
  const dcf = valuation.dcf
  const upside = calcUpside(dcf?.intrinsic_value, price.current)

  // Median comps multiples
  const validPE = valuation.comps
    .map((c) => c.pe)
    .filter((v): v is number => v != null && v > 0)
  const medianPE =
    validPE.length > 0 ? validPE.sort((a, b) => a - b)[Math.floor(validPE.length / 2)] : null

  const validEVEB = valuation.comps
    .map((c) => c.ev_ebitda)
    .filter((v): v is number => v != null && v > 0)
  const medianEVEB =
    validEVEB.length > 0 ? validEVEB.sort((a, b) => a - b)[Math.floor(validEVEB.length / 2)] : null

  return (
    <div className="space-y-6">
      {/* Charts row */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="border-border/40 lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              Price History (1Y)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PriceChart ticker={ticker} />
          </CardContent>
        </Card>

        <Card className="border-border/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              Revenue & Net Margin (5Y)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RevenueMarginChart data={data.financials.income_statement} />
          </CardContent>
        </Card>
      </div>

      {/* Ratio row */}
      <Card className="border-border/40">
        <CardContent className="p-4">
          <div className="grid grid-cols-3 gap-4 sm:grid-cols-6">
            <RatioItem label="Net Margin" value={fmtPct(ratios.net_margin)} />
            <RatioItem label="ROE" value={fmtPct(ratios.roe)} />
            <RatioItem label="ROIC" value={fmtPct(ratios.roic)} />
            <RatioItem label="D/E Ratio" value={fmtMultiple(ratios.debt_equity)} />
            <RatioItem label="Rev CAGR 3Y" value={fmtPct(ratios.revenue_cagr_3y)} />
            <RatioItem label="EPS CAGR 3Y" value={fmtPct(ratios.eps_cagr_3y)} />
          </div>
        </CardContent>
      </Card>

      {/* Valuation summary */}
      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Valuation Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <p className="text-xs text-muted-foreground">DCF Intrinsic Value</p>
              <p className="mt-1 tabular-nums text-lg font-semibold">
                {dcf?.intrinsic_value != null ? fmtINR(dcf.intrinsic_value) : "—"}
              </p>
              {dcf?.diverges_materially ? (
                <p className="mt-0.5 text-xs text-amber-400/80 leading-snug">
                  FCFF DCF is sensitive to capex assumptions — see Valuation tab
                </p>
              ) : (
                <p className={`mt-0.5 text-xs font-medium ${
                  upside == null ? "text-muted-foreground"
                    : upside >= 0 ? "text-emerald-500" : "text-red-500"
                }`}>
                  {upside != null
                    ? `${upside >= 0 ? "+" : ""}${fmtPct(upside)} vs current`
                    : "—"}
                </p>
              )}
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Median Peer P/E</p>
              <p className="mt-1 tabular-nums text-lg font-semibold">
                {fmtMultiple(medianPE)}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {valuation.comps.length} peers
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Median EV/EBITDA</p>
              <p className="mt-1 tabular-nums text-lg font-semibold">
                {fmtMultiple(medianEVEB)}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {company.sector ?? "—"}
              </p>
            </div>
          </div>

          {company.description && (
            <>
              <Separator className="my-4" />
              <p className="text-sm text-muted-foreground leading-relaxed line-clamp-4">
                {company.description}
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
