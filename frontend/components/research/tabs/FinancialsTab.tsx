"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { fmtCr, fmtEPS, fmtDelta, deltaDirection } from "@/lib/formatters"
import type { Research } from "@/lib/schemas"
import { cn } from "@/lib/utils"

interface Props {
  data: Research
}

type StatementType = "income" | "balance" | "cashflow"

function yoyDelta(rows: { year: number; [k: string]: number | null }[], field: string, idx: number) {
  if (idx === 0) return null
  const curr = rows[idx][field] as number | null
  const prev = rows[idx - 1][field] as number | null
  if (curr == null || prev == null || prev === 0) return null
  return (curr - prev) / Math.abs(prev)
}

function DeltaCell({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground/40">—</span>
  const dir = deltaDirection(value)
  return (
    <span
      className={cn(
        "text-xs font-medium",
        dir === "up" && "text-emerald-500",
        dir === "down" && "text-red-500",
        dir === "neutral" && "text-muted-foreground"
      )}
    >
      {fmtDelta(value)}
    </span>
  )
}

export function FinancialsTab({ data }: Props) {
  const [stmt, setStmt] = useState<StatementType>("income")
  const { income_statement, balance_sheet, cash_flow } = data.financials

  type AnyRow = { year: number; [k: string]: number | null }

  const config: Record<
    StatementType,
    { rows: AnyRow[]; fields: { key: string; label: string; fmt: (v: number | null) => string }[] }
  > = {
    income: {
      rows: income_statement as AnyRow[],
      fields: [
        { key: "revenue", label: "Revenue", fmt: fmtCr },
        { key: "gross_profit", label: "Gross Profit", fmt: fmtCr },
        { key: "operating_income", label: "Operating Income", fmt: fmtCr },
        { key: "net_income", label: "Net Income", fmt: fmtCr },
        { key: "eps", label: "EPS (₹)", fmt: fmtEPS },
      ],
    },
    balance: {
      rows: balance_sheet as AnyRow[],
      fields: [
        { key: "total_assets", label: "Total Assets", fmt: fmtCr },
        { key: "total_debt", label: "Total Debt", fmt: fmtCr },
        { key: "equity", label: "Shareholders' Equity", fmt: fmtCr },
        { key: "cash", label: "Cash & Equivalents", fmt: fmtCr },
      ],
    },
    cashflow: {
      rows: cash_flow as AnyRow[],
      fields: [
        { key: "operating_cf", label: "Operating Cash Flow", fmt: fmtCr },
        { key: "capex", label: "Capital Expenditure", fmt: fmtCr },
        { key: "free_cash_flow", label: "Free Cash Flow", fmt: fmtCr },
      ],
    },
  }

  const { rows, fields } = config[stmt]

  return (
    <Card className="border-border/40">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-sm font-medium">Financial Statements</CardTitle>
        <Select value={stmt} onValueChange={(v) => setStmt(v as StatementType)}>
          <SelectTrigger className="h-8 w-48 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="income">Income Statement</SelectItem>
            <SelectItem value="balance">Balance Sheet</SelectItem>
            <SelectItem value="cashflow">Cash Flow</SelectItem>
          </SelectContent>
        </Select>
      </CardHeader>
      <CardContent className="p-0 pb-4">
        <ScrollArea>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="sticky left-0 z-10 min-w-[180px] bg-card">
                  Metric (₹ Crore)
                </TableHead>
                {rows.map((row, i) => (
                  <TableHead key={row.year} className="text-right tabular-nums">
                    FY{row.year}
                    {i > 0 && (
                      <span className="ml-1 text-[10px] text-muted-foreground/60">
                        YoY
                      </span>
                    )}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {fields.map(({ key, label, fmt }) => (
                <TableRow key={key} className="hover:bg-muted/30">
                  <TableCell className="sticky left-0 z-10 bg-card text-sm font-medium">
                    {label}
                  </TableCell>
                  {rows.map((row, i) => {
                    const val = row[key] as number | null
                    const delta = yoyDelta(rows, key, i)
                    return (
                      <TableCell key={row.year} className="text-right tabular-nums">
                        <div className="flex flex-col items-end gap-0.5">
                          <span className="text-sm">
                            {val != null ? fmt(val) : "—"}
                          </span>
                          {i > 0 && <DeltaCell value={delta} />}
                        </div>
                      </TableCell>
                    )
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
