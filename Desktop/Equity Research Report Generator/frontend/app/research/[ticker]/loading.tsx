import { Skeleton } from "@/components/ui/skeleton"

export default function ResearchLoading() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      {/* Company header skeleton */}
      <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-8 w-64" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-24 rounded-full" />
            <Skeleton className="h-5 w-32 rounded-full" />
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-5 w-20" />
        </div>
      </div>

      {/* Metric cards */}
      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>

      {/* Tabs skeleton */}
      <div className="mb-4 flex gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-24 rounded-md" />
        ))}
      </div>

      {/* Content skeleton */}
      <Skeleton className="h-96 rounded-xl" />
    </div>
  )
}
