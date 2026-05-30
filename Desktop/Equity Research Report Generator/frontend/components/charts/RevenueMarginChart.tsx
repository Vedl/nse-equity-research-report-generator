"use client"

import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import { fmtCr } from "@/lib/formatters"
import type { IncomeRow } from "@/lib/schemas"

interface Props {
  data: IncomeRow[]
}

export function RevenueMarginChart({ data }: Props) {
  if (!data.length) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        No financial data available
      </div>
    )
  }

  const chartData = data.map((row) => ({
    year: `FY${row.year}`,
    revenue: row.revenue != null ? row.revenue / 1e7 : null, // to ₹Cr
    net_margin:
      row.net_income != null && row.revenue != null && row.revenue !== 0
        ? (row.net_income / row.revenue) * 100
        : null,
  }))

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis
          dataKey="year"
          tick={{ fontSize: 11, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          yAxisId="rev"
          orientation="left"
          tick={{ fontSize: 10, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `₹${Math.round(v).toLocaleString("en-IN")}Cr`}
          width={70}
        />
        <YAxis
          yAxisId="margin"
          orientation="right"
          tick={{ fontSize: 10, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${v.toFixed(0)}%`}
          width={40}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          formatter={(value: number, name: string) => {
            if (name === "Revenue") return [fmtCr(value * 1e7), name]
            if (name === "Net Margin") return [`${value.toFixed(1)}%`, name]
            return [value, name]
          }}
          labelStyle={{ color: "#e2e8f0" }}
        />
        <Legend
          wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }}
          iconType="circle"
          iconSize={8}
        />
        <Bar
          yAxisId="rev"
          dataKey="revenue"
          name="Revenue"
          fill="#0ea5e9"
          fillOpacity={0.7}
          radius={[3, 3, 0, 0]}
        />
        <Line
          yAxisId="margin"
          type="monotone"
          dataKey="net_margin"
          name="Net Margin"
          stroke="#10b981"
          strokeWidth={2}
          dot={{ fill: "#10b981", r: 3 }}
          activeDot={{ r: 5 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
