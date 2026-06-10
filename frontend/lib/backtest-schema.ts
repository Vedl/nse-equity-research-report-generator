import { z } from "zod"

const nullableNum = z.number().nullable()

export const FactorResultSchema = z.object({
  factor_name: z.string(),
  long_label: z.string(),
  short_label: z.string(),
  period_start: z.string(),
  period_end: z.string(),
  long_annual_returns: z.array(z.number()),
  short_annual_returns: z.array(z.number()),
  benchmark_annual_returns: z.array(z.number()),
  spread_annual_returns: z.array(z.number()),
  long_cagr: z.number(),
  short_cagr: z.number(),
  benchmark_cagr: z.number(),
  spread_cagr: z.number(),
  long_sharpe: z.number(),
  short_sharpe: z.number(),
  spread_sharpe: z.number(),
  max_drawdown_long: z.number(),
  max_drawdown_short: z.number(),
  hit_rate: z.number(),
  ic_mean: nullableNum.optional(),
  cumulative_dates: z.array(z.string()),
  cumulative_long: z.array(z.number()),
  cumulative_short: z.array(z.number()),
  cumulative_benchmark: z.array(z.number()),
})

export const BacktestResultSchema = z.object({
  universe_size: z.number(),
  stocks_with_history: z.number(),
  backtest_start: z.string(),
  backtest_end: z.string(),
  benchmark: z.string(),
  rebalance_frequency: z.string(),
  factors: z.array(FactorResultSchema),
  caveats: z.array(z.string()),
  methodology_notes: z.array(z.string()),
})

export type FactorResult = z.infer<typeof FactorResultSchema>
export type BacktestResult = z.infer<typeof BacktestResultSchema>
