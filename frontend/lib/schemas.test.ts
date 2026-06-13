import { describe, it, expect } from "vitest"
import { ResearchSchema } from "./schemas"

// Baseline valid /api/research/{ticker} payload. Every required field is
// present; optional/nullable sub-objects are set to their "absent" form.
// Tests below mutate only `valuation.india` to lock that contract.
function makeResearch(): Record<string, unknown> {
  return {
    company: {
      name: "Reliance Industries Ltd.",
      ticker: "RELIANCE.NS",
      sector: "Energy",
      industry: "Oil & Gas Refining & Marketing",
      description: "Conglomerate.",
    },
    price: {
      current: 1400,
      change: 12,
      change_pct: 0.86,
      week_52_low: 1100,
      week_52_high: 1600,
      market_cap: 19_000_000_000_000,
      market_cap_usd: 228_000_000_000,
    },
    financials: {
      income_statement: [],
      balance_sheet: [],
      cash_flow: [],
    },
    ratios: {
      gross_margin: 0.3,
      operating_margin: 0.12,
      net_margin: 0.08,
      roe: 0.09,
      roic: 0.07,
      current_ratio: 1.1,
      quick_ratio: 0.8,
      debt_equity: 0.4,
      interest_coverage: 5,
      asset_turnover: 0.5,
      revenue_cagr_3y: 0.15,
      eps_cagr_3y: 0.1,
    },
    valuation: {
      model_used: "sotp",
      route_reason: "Conglomerate with multiple reportable segments",
      confidence: "medium",
      intrinsic_value: 1500,
      market_divergence_pct: 0.07,
      diverges_materially: false,
      dcf: null,
      residual_income: null,
      excess_return: null,
      relative: null,
      comps: [],
      // financial / sotp / path_to_breakeven / india / broker_* are optional
    },
  }
}

const fullIndia = {
  primary_multiple: "ev_ebitda",
  sector_note: "note",
  is_psu: false,
  psu_discount_pct: 0,
  promoter_score: 75,
  promoter_premium_pct: 0,
  promoter_flags: [],
  group_adjustment_pct: 0,
  earnings_quality_score: 80,
  accruals_ratio: 0.1,
  cfo_ebitda_ratio: 0.9,
  earnings_quality_flags: [],
  implied_revenue_cagr: 0.12,
  dcf_vs_price_gap_pct: 0.05,
  adjusted_dcf_value: 1500,
  blended_value: 1480,
  blended_upside_pct: 0.06,
  narrative_bullets: [],
  diverges_materially: false,
}

describe("ResearchSchema — valuation.india contract", () => {
  // Regression for the RELIANCE "Failed to load research data" bug.
  // SOTP-routed conglomerates skip the India adjustment, so the backend
  // serializes `valuation.india: null`. The schema must accept it.
  it("accepts valuation.india === null (SOTP conglomerate, e.g. RELIANCE)", () => {
    const payload = makeResearch()
    ;(payload.valuation as Record<string, unknown>).india = null

    const result = ResearchSchema.safeParse(payload)
    expect(result.success).toBe(true)
  })

  it("accepts valuation.india absent (key omitted)", () => {
    const result = ResearchSchema.safeParse(makeResearch())
    expect(result.success).toBe(true)
  })

  it("accepts a fully-populated valuation.india object", () => {
    const payload = makeResearch()
    ;(payload.valuation as Record<string, unknown>).india = fullIndia

    const result = ResearchSchema.safeParse(payload)
    expect(result.success).toBe(true)
  })

  it("still rejects a malformed valuation.india (wrong shape)", () => {
    const payload = makeResearch()
    ;(payload.valuation as Record<string, unknown>).india = "not-an-object"

    const result = ResearchSchema.safeParse(payload)
    expect(result.success).toBe(false)
  })
})
