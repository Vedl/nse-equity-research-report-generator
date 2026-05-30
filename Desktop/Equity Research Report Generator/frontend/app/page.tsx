import { HeroSearch } from "@/components/landing/HeroSearch"
import { FeaturedGrid } from "@/components/landing/FeaturedGrid"
import { HowItWorks } from "@/components/landing/HowItWorks"

export default function HomePage() {
  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="relative flex flex-col items-center justify-center px-4 pt-20 pb-16 text-center sm:pt-28 sm:pb-20">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-sky-950/20 via-background to-background" />
        <span className="mb-4 inline-flex items-center rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs font-medium text-sky-400">
          Live data · 504 Nifty 500 companies
        </span>
        <h1 className="mb-4 max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
          Equity research for any{" "}
          <span className="text-sky-500">Nifty 500</span> company
        </h1>
        <p className="mb-10 max-w-xl text-base text-muted-foreground sm:text-lg">
          DCF valuation, financial analysis, comparable companies, and
          downloadable PDF reports — powered by real market data.
        </p>
        <HeroSearch />
      </section>

      {/* Featured companies */}
      <section className="mx-auto w-full max-w-7xl px-4 pb-16 sm:px-6">
        <h2 className="mb-6 text-sm font-medium uppercase tracking-widest text-muted-foreground">
          Featured companies
        </h2>
        <FeaturedGrid />
      </section>

      {/* How it works */}
      <section className="border-t border-border/40 bg-card/30 px-4 py-16 sm:px-6">
        <div className="mx-auto max-w-7xl">
          <h2 className="mb-10 text-center text-2xl font-bold tracking-tight">
            How it works
          </h2>
          <HowItWorks />
        </div>
      </section>
    </div>
  )
}
