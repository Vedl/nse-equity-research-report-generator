/**
 * Client-side DCF recalculation — pure TypeScript, no API call.
 *
 * Used by DCFSliders.tsx to update the intrinsic value in real-time
 * as the user drags the WACC, terminal growth, and horizon sliders.
 *
 * Formula mirrors equity_research/analysis/dcf.py exactly:
 *   FCFF_t = baseFCFF × (1 + g)^t
 *   EV = Σ FCFF_t / (1+wacc)^t  +  TV / (1+wacc)^n
 *   TV = FCFF_n × (1+tg) / (wacc - tg)
 *   Intrinsic = (EV - netDebt) / shares
 */

export function recalculateDCF(
  baseFCFF: number,
  growthRate: number,
  wacc: number,
  terminalGrowth: number,
  years: number,
  netDebt: number,
  shares: number
): number | null {
  if (!isFinite(wacc) || !isFinite(terminalGrowth)) return null
  if (wacc <= terminalGrowth) return null // Gordon growth model requires WACC > g
  if (shares <= 0) return null

  let pvSum = 0
  let fcff = baseFCFF

  for (let t = 1; t <= years; t++) {
    fcff = fcff * (1 + growthRate)
    pvSum += fcff / Math.pow(1 + wacc, t)
  }

  const tv = (fcff * (1 + terminalGrowth)) / (wacc - terminalGrowth)
  const pvTV = tv / Math.pow(1 + wacc, years)
  const ev = pvSum + pvTV
  const equityVal = ev - netDebt

  return equityVal / shares
}

/** Compute upside/downside percentage vs current price. */
export function calcUpside(
  intrinsic: number | null | undefined,
  current: number | null | undefined
): number | null {
  if (intrinsic == null || current == null || current === 0) return null
  return (intrinsic - current) / current
}
