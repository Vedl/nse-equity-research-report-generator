import { Badge } from "@/components/ui/badge"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { fmtINR, fmtPct } from "@/lib/formatters"
import type { Research } from "@/lib/schemas"

interface Props {
  data: Research
}

export function CompanyHeader({ data }: Props) {
  const { company, price } = data
  const change = price.change
  const changePct = price.change_pct

  const direction =
    change === null ? "neutral" : change > 0 ? "up" : change < 0 ? "down" : "neutral"

  const ChangeIcon =
    direction === "up"
      ? TrendingUp
      : direction === "down"
        ? TrendingDown
        : Minus

  const changeColor =
    direction === "up"
      ? "text-emerald-500"
      : direction === "down"
        ? "text-red-500"
        : "text-muted-foreground"

  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      {/* Left: name + badges */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          {company.name ?? company.ticker}
        </h1>
        <div className="mt-2 flex flex-wrap gap-2">
          <span className="font-mono text-sm text-muted-foreground">
            {company.ticker}
          </span>
          {company.sector && (
            <Badge variant="secondary" className="text-xs">
              {company.sector}
            </Badge>
          )}
          {company.industry && company.industry !== company.sector && (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              {company.industry}
            </Badge>
          )}
        </div>
      </div>

      {/* Right: price + change */}
      <div className="flex flex-col items-start gap-1 sm:items-end">
        <span className="tabular-nums text-3xl font-bold tracking-tight">
          {fmtINR(price.current)}
        </span>
        {change !== null && (
          <span className={`flex items-center gap-1 text-sm font-medium ${changeColor}`}>
            <ChangeIcon className="h-4 w-4" />
            <span className="tabular-nums">
              {fmtINR(Math.abs(change), 2)} ({fmtPct(Math.abs(changePct ?? 0))})
            </span>
          </span>
        )}
      </div>
    </div>
  )
}
