"use client"

import { useEffect, useRef } from "react"
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type AreaData,
} from "lightweight-charts"
import { usePrices } from "@/hooks/usePrices"
import { Skeleton } from "@/components/ui/skeleton"

interface Props {
  ticker: string
}

export function PriceChart({ ticker }: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartApiRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null)

  const { data: bars, isLoading } = usePrices(ticker, "1y")

  // Create chart once on mount
  useEffect(() => {
    if (!chartRef.current) return

    const chart = createChart(chartRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8", // slate-400
      },
      grid: {
        vertLines: { color: "#1e293b" }, // slate-800
        horzLines: { color: "#1e293b" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#1e293b" },
      timeScale: {
        borderColor: "#1e293b",
        timeVisible: true,
      },
      width: chartRef.current.clientWidth,
      height: 240,
    })

    const series = chart.addAreaSeries({
      lineColor: "#0ea5e9",   // sky-500
      topColor: "#0ea5e9",
      bottomColor: "rgba(14, 165, 233, 0.04)",
      lineWidth: 2,
      priceLineVisible: false,
    })

    chartApiRef.current = chart
    seriesRef.current = series

    // Responsive resize
    const ro = new ResizeObserver(() => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth })
      }
    })
    ro.observe(chartRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [])

  // Feed data whenever it changes
  useEffect(() => {
    if (!seriesRef.current || !bars?.length) return

    const chartData: AreaData[] = bars
      .filter((b) => b.close != null)
      .map((b) => ({
        time: b.time as `${number}-${number}-${number}`,
        value: b.close as number,
      }))
      .sort((a, b) => (a.time > b.time ? 1 : -1))

    seriesRef.current.setData(chartData)
    chartApiRef.current?.timeScale().fitContent()
  }, [bars])

  if (isLoading) return <Skeleton className="h-60 w-full rounded-lg" />

  return <div ref={chartRef} className="h-60 w-full" />
}
