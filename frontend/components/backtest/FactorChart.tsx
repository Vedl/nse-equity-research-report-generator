"use client"

import { useMemo } from "react"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import { FactorResult } from "@/lib/backtest-schema"

export default function FactorChart({ factor }: { factor: FactorResult }) {
  const data = useMemo(() => {
    return factor.cumulative_dates.map((date, i) => ({
      date,
      // Convert to log scale for better visual representation of compounding over 20 years
      Long: Math.log10(factor.cumulative_long[i]),
      Short: Math.log10(factor.cumulative_short[i]),
      Benchmark: Math.log10(factor.cumulative_benchmark[i]),
      // We keep the original values for the tooltip
      rawLong: factor.cumulative_long[i],
      rawShort: factor.cumulative_short[i],
      rawBench: factor.cumulative_benchmark[i],
    }))
  }, [factor])

  const formatTooltip = (
    value: number,
    name: string,
    props: { payload?: Record<string, number | undefined> }
  ) => {
    const rawVal = props.payload?.[`raw${name}`] ?? props.payload?.[`rawBench`]
    if (!rawVal) return [`${(Math.pow(10, value)).toFixed(2)}x`, name]
    return [`${rawVal.toFixed(2)}x`, name]
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={data}
        margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--muted))" />
        <XAxis 
          dataKey="date" 
          tickFormatter={(val) => val.split("-")[0]} // Just show Year
          minTickGap={30}
          stroke="hsl(var(--muted-foreground))"
          fontSize={12}
        />
        <YAxis 
          stroke="hsl(var(--muted-foreground))"
          fontSize={12}
          tickFormatter={(val) => Math.pow(10, val).toFixed(1) + "x"}
        />
        <Tooltip 
          formatter={formatTooltip}
          labelFormatter={(label) => `Date: ${label}`}
          contentStyle={{ 
            backgroundColor: "hsl(var(--background))",
            borderColor: "hsl(var(--border))",
            borderRadius: "6px"
          }}
        />
        <Legend />
        <Line 
          type="monotone" 
          dataKey="Long" 
          name="Long"
          stroke="#10b981" 
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line 
          type="monotone" 
          dataKey="Benchmark" 
          name="Bench"
          stroke="#94a3b8" 
          strokeWidth={2}
          strokeDasharray="5 5"
          dot={false}
        />
        <Line 
          type="monotone" 
          dataKey="Short" 
          name="Short"
          stroke="#ef4444" 
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
