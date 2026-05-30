import Link from "next/link"
import { AlertTriangle } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"

export default function TickerNotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-4 text-center">
      <AlertTriangle className="h-12 w-12 text-muted-foreground/40" />
      <h1 className="text-2xl font-bold">Ticker not found</h1>
      <p className="max-w-md text-muted-foreground">
        This ticker is not available in our dataset or yfinance has no data for
        it. Try one of the featured Nifty 500 companies on the home page.
      </p>
      <Link href="/" className={buttonVariants({ variant: "default" })}>
        Back to home
      </Link>
    </div>
  )
}
