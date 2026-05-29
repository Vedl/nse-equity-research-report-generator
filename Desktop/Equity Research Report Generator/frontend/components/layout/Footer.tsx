import Link from "next/link"
import { Github } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"

const TECH_STACK = [
  "Next.js 14",
  "FastAPI",
  "Railway",
  "yfinance",
  "WeasyPrint",
  "TailwindCSS",
]

export function Footer() {
  return (
    <footer className="border-t border-border/40 bg-background/95 mt-16">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        {/* Disclaimer */}
        <p className="text-xs text-muted-foreground text-center leading-relaxed max-w-2xl mx-auto">
          <strong>Not investment advice.</strong> All reports are generated for
          educational and portfolio demonstration purposes only. Financial data
          sourced from Yahoo Finance via yfinance. Valuations are illustrative —
          not recommendations to buy or sell any security.
        </p>

        <Separator className="my-6" />

        <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between">
          {/* Tech stack */}
          <div className="flex flex-wrap justify-center gap-1.5">
            {TECH_STACK.map((tech) => (
              <Badge
                key={tech}
                variant="outline"
                className="text-xs text-muted-foreground"
              >
                {tech}
              </Badge>
            ))}
          </div>

          {/* GitHub */}
          <Link
            href="https://github.com/laddavedant"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            aria-label="GitHub profile"
          >
            <Github className="h-4 w-4" />
            <span>laddavedant</span>
          </Link>
        </div>
      </div>
    </footer>
  )
}
