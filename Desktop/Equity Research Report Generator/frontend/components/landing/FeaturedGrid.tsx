import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"

const FEATURED = [
  { ticker: "RELIANCE", name: "Reliance Industries", sector: "Energy" },
  { ticker: "TCS", name: "Tata Consultancy Services", sector: "Technology" },
  { ticker: "HDFCBANK", name: "HDFC Bank", sector: "Financial Services" },
  { ticker: "INFY", name: "Infosys", sector: "Technology" },
  { ticker: "ICICIBANK", name: "ICICI Bank", sector: "Financial Services" },
  { ticker: "HINDUNILVR", name: "Hindustan Unilever", sector: "Consumer" },
  { ticker: "BAJFINANCE", name: "Bajaj Finance", sector: "Financial Services" },
  { ticker: "MARUTI", name: "Maruti Suzuki", sector: "Automotive" },
  { ticker: "WIPRO", name: "Wipro", sector: "Technology" },
  { ticker: "ASIANPAINT", name: "Asian Paints", sector: "Materials" },
] as const

const SECTOR_COLORS: Record<string, string> = {
  "Energy": "bg-amber-500/10 text-amber-400 border-amber-500/20",
  "Technology": "bg-sky-500/10 text-sky-400 border-sky-500/20",
  "Financial Services": "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  "Consumer": "bg-purple-500/10 text-purple-400 border-purple-500/20",
  "Automotive": "bg-orange-500/10 text-orange-400 border-orange-500/20",
  "Materials": "bg-rose-500/10 text-rose-400 border-rose-500/20",
}

export function FeaturedGrid() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
      {FEATURED.map((co) => (
        <Link key={co.ticker} href={`/research/${co.ticker}.NS`}>
          <Card className="group h-full cursor-pointer border-border/40 bg-card/60 transition-all hover:border-sky-500/40 hover:bg-card hover:shadow-md hover:shadow-sky-500/5">
            <CardContent className="flex flex-col justify-between p-4">
              <div>
                <p className="font-mono text-sm font-semibold tabular-nums">
                  {co.ticker}
                </p>
                <p className="mt-1 text-xs text-muted-foreground leading-snug line-clamp-2">
                  {co.name}
                </p>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span
                  className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                    SECTOR_COLORS[co.sector] ??
                    "bg-zinc-500/10 text-zinc-400 border-zinc-500/20"
                  }`}
                >
                  {co.sector}
                </span>
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-sky-400" />
              </div>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}
