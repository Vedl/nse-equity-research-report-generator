# Equity Research Tool — Frontend

## What this is
A public-facing financial research dashboard for recruiters and hiring managers.
It will be shared as a live link. It must look and feel like production software.

## Stack
Next.js 14 (App Router) + TypeScript strict mode
Tailwind CSS + shadcn/ui
TanStack Query v5 for all data fetching and caching
TradingView Lightweight Charts for the price chart
Recharts for revenue, margin, and ratio charts
Deployed on Vercel (free Hobby plan)

## Backend
Live at: https://equity-research-api-production.up.railway.app
All data is real — no mock data anywhere in the frontend.

## API base URL
Development: http://localhost:8000
Production: NEXT_PUBLIC_API_URL env var set in Vercel

## Conventions
TypeScript strict — no `any`, no untyped responses. Validate all API responses with Zod.
All data fetching via TanStack Query. Cache research responses 10 min (stale-while-revalidate).
Every data section has a Skeleton loading state and a typed error state. No blank spaces.
Prefer server components for initial fetches. Client components only where interactivity is needed.
Numbers always formatted with Intl.NumberFormat or shared utils. Never raw JS floats.
Mobile-first. All layouts work at 375px.
Dark mode on by default using Tailwind dark: variant.
No secrets in frontend code.

## Hard rules
The Download PDF button calls the backend — no client-side PDF generation.
Every research page shows "Not investment advice — for educational purposes only" in the footer.
GitHub link in the footer.
Do not use useEffect for data fetching. Use TanStack Query.
