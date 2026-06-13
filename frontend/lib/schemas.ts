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
    model_used: z.string(),
    route_reason: z.string().nullable(),
    confidence: z.string().nullable(),
    intrinsic_value: nullableNum,
    market_divergence_pct: nullableNum,
    diverges_materially: z.boolean(),
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
    residual_income: z
      .object({
        intrinsic_value: nullableNum,
        book_value_per_share: nullableNum,
        cost_of_equity: nullableNum,
        growth_rate: nullableNum,
        terminal_growth: nullableNum,
        shares_outstanding: nullableNum,
      })
      .nullable(),
    excess_return: z
      .object({
        intrinsic_value: nullableNum,
        book_value_per_share: nullableNum,
        cost_of_equity: nullableNum,
        roe: nullableNum,
        sustainable_growth: nullableNum,
        terminal_growth: nullableNum,
        shares_outstanding: nullableNum,
        is_pb_fallback: z.boolean().nullable(),
      })
      .nullable(),
    relative: z
      .object({
        low: nullableNum,
        high: nullableNum,
        median: nullableNum,
        implied_pe: nullableNum,
        implied_ev_ebitda: nullableNum,
        implied_pb: nullableNum,
        implied_ev_sales: nullableNum,
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
    financial: z
      .object({
        justified_pb: nullableNum,
        intrinsic_value: nullableNum,
        book_value_per_share: nullableNum,
        cost_of_equity: nullableNum,
        roe: nullableNum,
        growth_rate: nullableNum,
        retention_ratio: nullableNum,
        roe_ke_spread: nullableNum,
        shares_outstanding: nullableNum,
        sensitivity_roe_labels: z.array(z.number()),
        sensitivity_ke_labels: z.array(z.number()),
        sensitivity_pb: z.array(z.array(nullableNum)),
        is_fallback: z.boolean(),
        fallback_note: z.string(),
        bank_metrics: z.object({
          net_interest_margin: nullableNum,
          gross_npa_ratio: nullableNum,
          credit_cost: nullableNum,
          casa_ratio: nullableNum,
          tier1_ratio: nullableNum,
        }),
      })
      .nullable()
      .optional(),
    sotp: z
      .object({
        total_ebitda: nullableNum,
        total_ev: nullableNum,
        net_debt: nullableNum,
        equity_value: nullableNum,
        shares_outstanding: nullableNum,
        intrinsic_value: nullableNum,
        blended_ev_ebitda: nullableNum,
        is_fallback: z.boolean(),
        fallback_note: z.string(),
        segments: z.array(
          z.object({
            name: z.string(),
            ebitda_share: nullableNum,
            ev_ebitda_multiple: nullableNum,
            segment_ebitda: nullableNum,
            segment_ev: nullableNum,
            note: z.string(),
          })
        ),
      })
      .nullable()
      .optional(),
    path_to_breakeven: z
      .object({
        cash_runway_quarters: nullableNum,
        breakeven_revenue: nullableNum,
        current_revenue: nullableNum,
        gap_to_breakeven_pct: nullableNum,
        gross_margin: nullableNum,
      })
      .nullable()
      .optional(),
    india: z
      .object({
        primary_multiple: z.string(),
        sector_note: z.string(),
        is_psu: z.boolean(),
        psu_discount_pct: z.number(),
        promoter_score: z.number(),
        promoter_premium_pct: z.number(),
        promoter_flags: z.array(z.string()),
        group_adjustment_pct: z.number(),
        earnings_quality_score: z.number(),
        accruals_ratio: z.number(),
        cfo_ebitda_ratio: z.number(),
        earnings_quality_flags: z.array(z.string()),
        implied_revenue_cagr: z.number(),
        dcf_vs_price_gap_pct: z.number(),
        adjusted_dcf_value: z.number(),
        blended_value: z.number(),
        blended_upside_pct: z.number(),
        narrative_bullets: z.array(z.string()),
        diverges_materially: z.boolean(),
      })
      // SOTP-routed conglomerates (e.g. RELIANCE) skip the India adjustment,
      // so the backend emits `india: null`. Must be nullable like every other
      // optional valuation sub-object, not just optional.
      .nullable()
      .optional(),
    broker_target_price: nullableNum.optional(),
    broker_recommendation: z.string().nullable().optional(),
    broker_analyst_count: z.number().nullable().optional(),
    broker_upside_pct: nullableNum.optional(),
    model_vs_broker_pct: nullableNum.optional(),
  }),
})

export type Research = z.infer<typeof ResearchSchema>
export type TickerItem = z.infer<typeof TickerItemSchema>
export type PriceBar = z.infer<typeof PriceBarSchema>
export type DCF = NonNullable<Research["valuation"]["dcf"]>
export type ResidualIncome = NonNullable<Research["valuation"]["residual_income"]>
export type ExcessReturn = NonNullable<Research["valuation"]["excess_return"]>
export type FinancialValuation = NonNullable<Research["valuation"]["financial"]>
export type SOTPValuation = NonNullable<Research["valuation"]["sotp"]>
export type PathToBreakeven = NonNullable<Research["valuation"]["path_to_breakeven"]>
export type RelativeValuation = NonNullable<Research["valuation"]["relative"]>
export type Comp = Research["valuation"]["comps"][number]
export type IncomeRow = Research["financials"]["income_statement"][number]
export type BalanceRow = Research["financials"]["balance_sheet"][number]
export type CashFlowRow = Research["financials"]["cash_flow"][number]
