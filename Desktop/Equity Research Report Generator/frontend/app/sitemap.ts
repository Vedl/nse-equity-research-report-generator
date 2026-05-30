import type { MetadataRoute } from "next"

const FEATURED_TICKERS = [
  "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
  "HINDUNILVR", "BAJFINANCE", "MARUTI", "WIPRO", "ASIANPAINT",
]

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://equity-research.vercel.app"

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1,
    },
    ...FEATURED_TICKERS.map((ticker) => ({
      url: `${BASE_URL}/research/${ticker}.NS`,
      lastModified: new Date(),
      changeFrequency: "daily" as const,
      priority: 0.9,
    })),
  ]
}
