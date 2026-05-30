import { Card, CardContent } from "@/components/ui/card"
import { TrendingUp, TrendingDown, DollarSign, Target, BarChart2, Info } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { fmtINR, fmtCr, fmtUSD, fmtPct } from "@/lib/formatters"
import { calcUpside } from "@/lib/dcf"
import type { Research } from "@/lib/schemas"

interface Props {
  data: Research
}

export function MetricCards({ data }: Props) {
  const { price, valuation } = data
  const dcf = valuation.dcf
  const dcfValue = dcf?.intrinsic_value ?? null
  const divergesMaterially = dcf?.diverges_materially ?? false
  const upside = calcUpside(dcfValue, price.current)

  // DCF/Upside card adapts based on diverges_materially flag.
  // When the FCFF model diverges >35% from the market price (common for
  // capex-heavy companies), we display the intrinsic value with a context
  // caption instead of a headline "Downside -85%" which would look broken.
  const upsideCard = divergesMaterially
    ? {
        label: "DCF Target",
        icon: Info,
        content: (
          <div className="mt-1">
            <span className="tabular-nums text-xl font-semibold">
              {dcfValue != null ? fmtINR(dcfValue) : "—"}
            </span>
            <Tooltip>
              <TooltipTrigger
                render={<p className="mt-1 text-xs text-amber-400/80 cursor-help leading-snug" />}
              >
                  FCFF DCF is sensitive to capex assumptions →{" "}
                  <span className="underline decoration-dotted">see details</span>
              </TooltipTrigger>
              <TooltipContent className="max-w-64 text-xs leading-relaxed">
                The FCFF model uses trailing free cash flow, which can understate
                capital-intensive or high-growth companies whose capex will generate
                future returns. See the Valuation tab for the full sensitivity
                analysis and assumptions appendix.
              </TooltipContent>
            </Tooltip>
          </div>
        ),
      }
    : {
        label: upside != null && upside >= 0 ? "Upside" : "Downside",
        icon: upside != null && upside >= 0 ? TrendingUp : TrendingDown,
        content: (
          <div className="mt-1">
            <span
              className={`tabular-nums text-xl font-semibold ${
                upside == null
                  ? "text-muted-foreground"
                  : upside >= 0
                    ? "text-emerald-500"
                    : "text-red-500"
              }`}
            >
              {upside != null
                ? `${upside >= 0 ? "+" : ""}${fmtPct(upside)}`
                : "—"}
            </span>
            <p className="mt-0.5 text-xs text-muted-foreground">vs current price</p>
          </div>
        ),
      }

  const cards = [
    {
      label: "52-Week Range",
      icon: BarChart2,
      content: (
        <div className="mt-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span className="tabular-nums">{fmtINR(price.week_52_low)}</span>
            <span className="tabular-nums">{fmtINR(price.week_52_high)}</span>
          </div>
          {price.week_52_low != null &&
            price.week_52_high != null &&
            price.current != null && (
              <div className="relative h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="absolute left-0 h-full rounded-full bg-sky-500"
                  style={{
                    width: `${Math.min(100, Math.max(0,
                      ((price.current - price.week_52_low) /
                        (price.week_52_high - price.week_52_low)) * 100
                    ))}%`,
                  }}
                />
              </div>
            )}
        </div>
      ),
    },
    {
      label: "Market Cap",
      icon: DollarSign,
      content: (
        <div className="mt-1 flex flex-col gap-0.5">
          <span className="tabular-nums text-xl font-semibold">
            {fmtCr(price.market_cap)}
          </span>
          <span className="tabular-nums text-xs text-muted-foreground">
            {fmtUSD(price.market_cap_usd)}
          </span>
        </div>
      ),
    },
    {
      label: "DCF Intrinsic",
      icon: Target,
      content: (
        <div className="mt-1">
          <span className="tabular-nums text-xl font-semibold">
            {dcfValue != null ? fmtINR(dcfValue) : "—"}
          </span>
          {dcfValue != null && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Intrinsic value / share
            </p>
          )}
        </div>
      ),
    },
    upsideCard,
  ]

  return (
    <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <Card key={card.label} className="border-border/40">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Icon className="h-3.5 w-3.5" />
                {card.label}
              </div>
              {card.content}
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
