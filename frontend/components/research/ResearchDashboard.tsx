"use client"

import { notFound } from "next/navigation"
import { AlertCircle } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent } from "@/components/ui/card"
import { useResearch } from "@/hooks/useResearch"
import { CompanyHeader } from "./CompanyHeader"
import { MetricCards } from "./MetricCards"
import { OverviewTab } from "./tabs/OverviewTab"
import { FinancialsTab } from "./tabs/FinancialsTab"
import { ValuationTab } from "./tabs/ValuationTab"
import { ReportTab } from "./tabs/ReportTab"
import { ResearchSkeleton } from "./ResearchSkeleton"

interface Props {
  ticker: string
}

export function ResearchDashboard({ ticker }: Props) {
  const { data, isLoading, isError, error } = useResearch(ticker)

  if (isLoading) return <ResearchSkeleton />

  if (isError) {
    // 404 from API → render Next.js not-found page
    if (error?.message?.includes("404")) notFound()

    return (
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-start gap-3 p-6">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <div>
              <p className="font-medium text-destructive">
                Failed to load research data
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {error?.message ?? "An unexpected error occurred."}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <CompanyHeader data={data} />
      <MetricCards data={data} />

      <Tabs defaultValue="overview" className="mt-6">
        <TabsList className="mb-6 grid w-full grid-cols-4 sm:w-auto sm:grid-cols-none sm:inline-flex">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="financials">Financials</TabsTrigger>
          <TabsTrigger value="valuation">Valuation</TabsTrigger>
          <TabsTrigger value="report">Report</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab data={data} ticker={ticker} />
        </TabsContent>
        <TabsContent value="financials">
          <FinancialsTab data={data} />
        </TabsContent>
        <TabsContent value="valuation">
          <ValuationTab data={data} />
        </TabsContent>
        <TabsContent value="report">
          <ReportTab ticker={ticker} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
