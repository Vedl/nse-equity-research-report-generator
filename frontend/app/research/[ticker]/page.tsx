import type { Metadata } from "next"
import { QueryClient, HydrationBoundary, dehydrate } from "@tanstack/react-query"
import { ResearchDashboard } from "@/components/research/ResearchDashboard"
import { fetchResearch, normaliseTicker } from "@/lib/api"
import { fmtINR } from "@/lib/formatters"

interface Props {
  params: { ticker: string }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const ticker = normaliseTicker(params.ticker)
  try {
    const data = await fetchResearch(ticker)
    const name = data.company.name ?? ticker
    const price = data.price.current ? fmtINR(data.price.current) : null
    const sector = data.company.sector ?? ""
    const dcf = data.valuation.dcf?.intrinsic_value
      ? fmtINR(data.valuation.dcf.intrinsic_value)
      : null
    const description = [name, price, sector, dcf ? `DCF ${dcf}` : null]
      .filter(Boolean)
      .join(" · ")
    return {
      title: `${ticker.replace(".NS", "")} — Equity Research`,
      description,
      openGraph: {
        title: `${ticker.replace(".NS", "")} — Equity Research`,
        description,
        type: "website",
      },
      twitter: { card: "summary_large_image" },
    }
  } catch {
    return {
      title: `${ticker.replace(".NS", "")} — Equity Research`,
    }
  }
}

export default async function ResearchPage({ params }: Props) {
  const ticker = normaliseTicker(params.ticker)
  const queryClient = new QueryClient()

  // Prefetch on the server — wrapped in try/catch so a cold or slow Railway
  // container falls through to client-side fetching (which shows skeletons)
  // instead of hanging the server render for 30+ seconds.
  try {
    await queryClient.prefetchQuery({
      queryKey: ["research", ticker],
      queryFn: () => fetchResearch(ticker),
    })
  } catch {
    // Intentionally swallowed — ResearchDashboard handles loading/error states
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ResearchDashboard ticker={ticker} />
    </HydrationBoundary>
  )
}
