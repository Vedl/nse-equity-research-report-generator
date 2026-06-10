import { BacktestDashboard } from "@/components/backtest/BacktestDashboard"
import { BacktestResultSchema } from "@/lib/backtest-schema"
import { API_URL } from "@/lib/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle } from "lucide-react"

// Render at request time — the backtest endpoint can take minutes on a cold
// backend, which times out Vercel's 60 s static-generation worker at build.
export const dynamic = "force-dynamic"
export const revalidate = 3600 // fetch-level cache: backtests don't change intraday

export default async function BacktestPage() {
  let data = null
  let errorMsg = null

  try {
    const res = await fetch(`${API_URL}/api/backtest`, { next: { revalidate: 3600 } })
    if (!res.ok) {
      throw new Error(`Failed to fetch backtest data: ${res.statusText}`)
    }
    const json = await res.json()
    data = BacktestResultSchema.parse(json)
  } catch (err) {
    errorMsg =
      err instanceof Error
        ? err.message
        : "An unknown error occurred while fetching backtest results."
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">India Valuation Factor Backtest</h1>
        <p className="mt-2 text-muted-foreground">
          20-year structural and dynamic factor backtesting engine for the Nifty 500 universe.
        </p>
      </div>

      {errorMsg ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error Loading Backtest</AlertTitle>
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      ) : data ? (
        <BacktestDashboard data={data} />
      ) : null}
    </main>
  )
}
