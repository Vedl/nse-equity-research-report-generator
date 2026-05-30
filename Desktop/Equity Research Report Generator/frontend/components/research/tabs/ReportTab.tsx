"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { FileDown, Loader2, CheckCircle, AlertCircle } from "lucide-react"
import { normaliseTicker } from "@/lib/api"

interface Props {
  ticker: string
}

const PDF_SECTIONS = [
  { title: "Company Snapshot", desc: "Current price, market cap, 52-week range, sector, and key ratios at a glance." },
  { title: "Business Overview", desc: "Company description and business model summary." },
  { title: "Financial Summary", desc: "5-year income statement, balance sheet, and cash flow statement." },
  { title: "Ratio Analysis", desc: "Profitability, liquidity, solvency, efficiency, and CAGR metrics." },
  { title: "DCF Valuation", desc: "FCFF model with WACC breakdown, 5-year projections, terminal value, and 5×5 sensitivity table." },
  { title: "Comparable Companies", desc: "Sector peer multiples: P/E, EV/EBITDA, P/B, EV/Sales." },
  { title: "Valuation Summary", desc: "Blended DCF and comps range, upside/downside vs current price." },
  { title: "Assumptions Appendix", desc: "Every assumption used: risk-free rate, ERP, tax rate, growth rates, terminal growth." },
]

type DownloadState = "idle" | "loading" | "success" | "error"

export function ReportTab({ ticker }: Props) {
  const [state, setState] = useState<DownloadState>("idle")
  const [elapsed, setElapsed] = useState(0)
  const [errMsg, setErrMsg] = useState("")

  async function handleDownload() {
    setState("loading")
    setElapsed(0)
    const start = Date.now()

    // Show elapsed seconds while downloading (WeasyPrint takes 15-40s)
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 1000)

    try {
      const normTicker = normaliseTicker(ticker)
      const res = await fetch(`/api/report/${normTicker}/pdf`)
      clearInterval(timer)

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `Server error ${res.status}`)
      }

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `${normTicker.replace(".NS", "")}_equity_research.pdf`
      a.click()
      URL.revokeObjectURL(url)
      setState("success")
      setTimeout(() => setState("idle"), 4000)
    } catch (e) {
      clearInterval(timer)
      setErrMsg(e instanceof Error ? e.message : "Download failed")
      setState("error")
      setTimeout(() => setState("idle"), 6000)
    }
  }

  return (
    <div className="space-y-6">
      {/* Download card */}
      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Download PDF Report</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            A professionally formatted multi-page PDF report generated from live market data.
            Report generation typically takes 15–40 seconds.
          </p>

          <Button
            size="lg"
            className="gap-2"
            onClick={handleDownload}
            disabled={state === "loading"}
          >
            {state === "loading" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating… {elapsed > 0 && `(${elapsed}s)`}
              </>
            ) : state === "success" ? (
              <>
                <CheckCircle className="h-4 w-4 text-emerald-400" />
                Downloaded
              </>
            ) : state === "error" ? (
              <>
                <AlertCircle className="h-4 w-4 text-destructive" />
                Retry
              </>
            ) : (
              <>
                <FileDown className="h-4 w-4" />
                Download PDF
              </>
            )}
          </Button>

          {state === "error" && errMsg && (
            <p className="text-sm text-destructive">{errMsg}</p>
          )}

          <p className="text-xs text-muted-foreground/60">
            ⚠️ Not investment advice — generated for educational and portfolio demonstration purposes only.
          </p>
        </CardContent>
      </Card>

      {/* Report sections */}
      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Report Contents</CardTitle>
        </CardHeader>
        <CardContent className="space-y-0">
          {PDF_SECTIONS.map((section, i) => (
            <div key={section.title}>
              <div className="flex gap-3 py-3">
                <span className="mt-0.5 font-mono text-xs text-sky-500/70 tabular-nums min-w-[20px]">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className="text-sm font-medium">{section.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{section.desc}</p>
                </div>
              </div>
              {i < PDF_SECTIONS.length - 1 && <Separator />}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
