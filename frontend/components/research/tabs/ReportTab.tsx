"use client"

import { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button, buttonVariants } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  FileDown,
  Loader2,
  CheckCircle,
  AlertCircle,
  ArrowRight,
  Circle,
} from "lucide-react"
import { normaliseTicker } from "@/lib/api"

interface Props {
  ticker: string
}

/** Pipeline steps emitted by the backend SSE stream, in order. */
const STEPS = [
  "Fetching financial data",
  "Computing valuation models",
  "Running quality screens (Piotroski, Beneish, Altman)",
  "Rendering charts",
  "Rendering PDF",
]

const PDF_SECTIONS = [
  { title: "Cover & Rating", desc: "BUY/HOLD/SELL call, CMP, 12-month target, investment thesis, key statistics." },
  { title: "Executive Summary & Valuation", desc: "Bear/base/bull band, model weights, price vs Nifty 50, confidence gauge, DCF sensitivity heat map." },
  { title: "Financial Summary", desc: "5-year history + 2-year estimates: revenue, EBITDA, PAT, EPS, FCFF, RoE, RoIC." },
  { title: "DuPont & Quality", desc: "5-factor ROE decomposition, Piotroski 9-signal scorecard, earnings quality, cash conversion cycle, ROIC vs WACC." },
  { title: "Comparable Companies", desc: "Peer multiples with median, premium/discount, implied values per share." },
  { title: "Risk & Governance", desc: "Beneish M-Score, Altman Z″, promoter scorecard, numbered risk factors." },
  { title: "Detailed Financials", desc: "Full P&L, balance sheet, cash flow (5 years) + every model assumption." },
]

type GenState = "idle" | "streaming" | "done" | "error"

export function ReportTab({ ticker }: Props) {
  const [state, setState] = useState<GenState>("idle")
  const [completedSteps, setCompletedSteps] = useState<string[]>([])
  const [currentStep, setCurrentStep] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [errMsg, setErrMsg] = useState("")
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => () => esRef.current?.close(), [])

  function startGeneration() {
    setState("streaming")
    setCompletedSteps([])
    setCurrentStep(STEPS[0])
    setPdfUrl(null)
    setErrMsg("")

    const t = normaliseTicker(ticker)
    const es = new EventSource(`/api/report/${t}/stream`)
    esRef.current = es

    es.addEventListener("progress", (ev) => {
      const { step } = JSON.parse((ev as MessageEvent).data)
      // Every step that precedes the one now starting is complete.
      const idx = STEPS.indexOf(step)
      setCompletedSteps(idx > 0 ? STEPS.slice(0, idx) : [])
      setCurrentStep(step)
    })
    es.addEventListener("done", (ev) => {
      const { url } = JSON.parse((ev as MessageEvent).data)
      setCompletedSteps(STEPS)
      setCurrentStep(null)
      setPdfUrl(url)
      setState("done")
      es.close()
    })
    es.addEventListener("error", (ev) => {
      const data = (ev as MessageEvent).data
      let message = "Report generation failed."
      try {
        message = JSON.parse(data).message ?? message
      } catch {
        /* connection-level error with no payload */
      }
      setErrMsg(message)
      setState("error")
      es.close()
    })
  }

  return (
    <div className="space-y-6">
      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">
            Generate Full Research Report
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            A 7-page institutional research note rendered from live market data —
            multi-stage DCF or sector-appropriate model, forensic quality screens,
            and a rated 12-month target. Generation takes 15–60 seconds.
          </p>

          <Button
            size="lg"
            className="gap-2"
            onClick={startGeneration}
            disabled={state === "streaming"}
          >
            {state === "streaming" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Generating…
              </>
            ) : (
              <>
                <FileDown className="h-4 w-4" /> Generate Full Research Report
              </>
            )}
          </Button>

          {/* Live progress tracker (SSE) */}
          {state !== "idle" && (
            <div className="space-y-1.5 rounded-md border border-border/40 bg-card/40 p-4 font-mono text-xs">
              {STEPS.map((step) => {
                const isDone = completedSteps.includes(step) || state === "done"
                const isCurrent = currentStep === step && state === "streaming"
                return (
                  <div key={step} className="flex items-center gap-2">
                    {isDone ? (
                      <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
                    ) : isCurrent ? (
                      <ArrowRight className="h-3.5 w-3.5 animate-pulse text-sky-400" />
                    ) : (
                      <Circle className="h-3.5 w-3.5 text-muted-foreground/40" />
                    )}
                    <span
                      className={
                        isDone
                          ? "text-foreground"
                          : isCurrent
                            ? "text-sky-400"
                            : "text-muted-foreground/60"
                      }
                    >
                      {step}
                    </span>
                  </div>
                )
              })}
            </div>
          )}

          {state === "error" && (
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" /> {errMsg}
            </p>
          )}

          {state === "done" && pdfUrl && (
            <div className="space-y-4">
              <a
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={buttonVariants({ variant: "default", size: "lg" }) + " gap-2"}
              >
                <FileDown className="h-4 w-4" /> Download PDF
              </a>
              <div className="overflow-hidden rounded-md border border-border/40">
                <iframe
                  src={pdfUrl}
                  title="Report preview"
                  className="h-[640px] w-full bg-white"
                />
              </div>
            </div>
          )}

          <p className="text-xs text-muted-foreground/60">
            ⚠️ Not investment advice — generated for educational and portfolio
            demonstration purposes only.
          </p>
        </CardContent>
      </Card>

      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Report Contents</CardTitle>
        </CardHeader>
        <CardContent className="space-y-0">
          {PDF_SECTIONS.map((section, i) => (
            <div key={section.title}>
              <div className="flex gap-3 py-3">
                <span className="mt-0.5 min-w-[20px] font-mono text-xs tabular-nums text-sky-500/70">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className="text-sm font-medium">{section.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {section.desc}
                  </p>
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
