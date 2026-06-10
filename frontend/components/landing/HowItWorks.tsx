import { Search, LineChart, FileDown } from "lucide-react"

const STEPS = [
  {
    icon: Search,
    number: "01",
    title: "Search a ticker",
    description:
      "Type any Nifty 500 company name or NSE ticker symbol. 504 companies covered with live data.",
  },
  {
    icon: LineChart,
    number: "02",
    title: "View full analysis",
    description:
      "Explore DCF valuation, financial statements, ratio analysis, and comparable company multiples.",
  },
  {
    icon: FileDown,
    number: "03",
    title: "Download the report",
    description:
      "Export a professionally formatted multi-page PDF with all assumptions, sensitivity tables, and a disclaimer.",
  },
]

export function HowItWorks() {
  return (
    <div className="grid gap-8 sm:grid-cols-3">
      {STEPS.map((step) => {
        const Icon = step.icon
        return (
          <div key={step.number} className="flex flex-col items-center text-center sm:items-start sm:text-left">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-sky-500/10 border border-sky-500/20">
              <Icon className="h-6 w-6 text-sky-500" />
            </div>
            <span className="mb-1 text-xs font-mono font-medium text-sky-500/70">
              {step.number}
            </span>
            <h3 className="mb-2 font-semibold tracking-tight">{step.title}</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {step.description}
            </p>
          </div>
        )
      })}
    </div>
  )
}
