import { z } from "zod"

// ── Shared primitive ────────────────────────────────────────────────────────
const nullableNum = z.number().nullable()

// ── /api/tickers ────────────────────────────────────────────────────────────
export const TickerItemSchema = z.object({
  ticker: z.string(),
  name: z.string(),
  sector: z.string(),
})
export const TickersSchema = z.array(TickerItemSchema)

// ── /api/prices/{ticker} ────────────────────────────────────────────────────
export const PriceBarSchema = z.object({
  time: z.string(), // "YYYY-MM-DD"
  open: nullableNum,
  high: nullableNum,
  low: nullableNum,
  close: nullableNum,
  volume: z.number().int().nullable(),
})
export const PricesSchema = z.array(PriceBarSchema)

// ── /api/research/{ticker} ──────────────────────────────────────────────────
export const ResearchSchema = z.object({
  company: z.object({
    name: z.string().nullable(),
    ticker: z.string(),
    sector: z.string().nullable(),
    industry: z.string().nullable(),
    description: z.string().nullable(),
  }),

  price: z.object({
    current: nullableNum,
    change: nullableNum,
    change_pct: nullableNum,
    week_52_low: nullableNum,
    week_52_high: nullableNum,
    market_cap: nullableNum,
    market_cap_usd: nullableNum,
  }),

  financials: z.object({
    income_statement: z.array(
      z.object({
        year: z.number().int(),
        revenue: nullableNum,
        gross_profit: nullableNum,
        operating_income: nullableNum,
        net_income: nullableNum,
        eps: nullableNum,
      })
    ),
    balance_sheet: z.array(
      z.object({
        year: z.number().int(),
        total_assets: nullableNum,
        total_debt: nullableNum,
        equity: nullableNum,
        cash: nullableNum,
      })
    ),
    cash_flow: z.array(
      z.object({
        year: z.number().int(),
        operating_cf: nullableNum,
        capex: nullableNum,
        free_cash_flow: nullableNum,
      })
    ),
  }),

  ratios: z.object({
    gross_margin: nullableNum,
    operating_margin: nullableNum,
    net_margin: nullableNum,
    roe: nullableNum,
    roic: nullableNum,
    current_ratio: nullableNum,
    quick_ratio: nullableNum,
    debt_equity: nullableNum,
    interest_coverage: nullableNum,
    asset_turnover: nullableNum,
    revenue_cagr_3y: nullableNum,
    eps_cagr_3y: nullableNum,
  }),

  valuation: z.object({
    dcf: z
      .object({
        intrinsic_value: nullableNum,
        sensitivity: z.array(z.array(nullableNum)),
        sensitivity_wacc_labels: z.array(z.number()).optional(),
        sensitivity_tg_labels: z.array(z.number()).optional(),
        assumptions: z.object({
          wacc: nullableNum,
          terminal_growth: nullableNum,
          projection_years: z.number().int().nullable(),
          risk_free_rate: nullableNum,
          erp: nullableNum,
        }),
        // Added by M0 for client-side DCF sliders
        base_fcff: nullableNum.optional(),
        growth_rate: nullableNum.optional(),
        net_debt: nullableNum.optional(),
        shares_outstanding: nullableNum.optional(),
        // Divergence flag: signals that FCFF DCF deviates >35% from market price.
        // True for capex-heavy/high-growth companies — not an error, just context.
        market_divergence_pct: nullableNum.optional(),
        diverges_materially: z.boolean().optional(),
      })
      .nullable(),
    comps: z.array(
      z.object({
        ticker: z.string(),
        name: z.string().nullable(),
        pe: nullableNum,
        ev_ebitda: nullableNum,
        pb: nullableNum,
        ev_sales: nullableNum,
      })
    ),
  }),
})

export type Research = z.infer<typeof ResearchSchema>
export type TickerItem = z.infer<typeof TickerItemSchema>
export type PriceBar = z.infer<typeof PriceBarSchema>
export type DCF = NonNullable<Research["valuation"]["dcf"]>
export type Comp = Research["valuation"]["comps"][number]
export type IncomeRow = Research["financials"]["income_statement"][number]
export type BalanceRow = Research["financials"]["balance_sheet"][number]
export type CashFlowRow = Research["financials"]["cash_flow"][number]
