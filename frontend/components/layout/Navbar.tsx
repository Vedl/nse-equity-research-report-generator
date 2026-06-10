"use client"

import Link from "next/link"
import { useTheme } from "next-themes"
import { Sun, Moon, BarChart2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TickerTape } from "@/components/layout/TickerTape"

export function Navbar() {
  const { theme, setTheme } = useTheme()

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <TickerTape />
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold tracking-tight hover:opacity-80 transition-opacity"
        >
          <BarChart2 className="h-5 w-5 text-sky-500" />
          <span className="text-foreground">NSE Research Engine</span>
        </Link>

        {/* Right side */}
        <div className="flex items-center gap-4">
          <Link
            href="/universe"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Universe
          </Link>
          <Link
            href="/reports"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Reports
          </Link>
          <Link
            href="/backtest"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Factor Backtest
          </Link>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Toggle dark mode"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          </Button>
        </div>
      </div>
    </header>
  )
}
