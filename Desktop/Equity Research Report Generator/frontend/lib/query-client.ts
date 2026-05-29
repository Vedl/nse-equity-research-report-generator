import { QueryClient } from "@tanstack/react-query"

/**
 * Shared QueryClient factory.
 *
 * staleTime 10 min  — research data is expensive to fetch; 10 min matches
 *                     the Railway backend TTLCache so the browser and server
 *                     stay in sync.
 * gcTime   30 min  — keep cached data in memory for 30 min after last use.
 * retry    1       — one retry for transient network errors.
 */
export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10 * 60 * 1000, // 10 min
        gcTime: 30 * 60 * 1000,    // 30 min
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  })
}
