# RECON.md — Repository Audit & Transformation Plan

*Audit date: 10 June 2026. Auditor: Claude (Fable 5), acting as senior financial
software engineer / CFA charterholder.*

---

## 1. Current Architecture (as found)

```
                         ┌──────────────────────────────────────────┐
                         │ Vercel — Next.js 14 frontend (dark theme)│
                         │  /            landing + search           │
                         │  /research/[ticker]  4-tab dashboard     │
                         │  /backtest    factor backtest viewer     │
                         └───────────────────┬──────────────────────┘
                                             │ NEXT_PUBLIC_API_URL
                                             ▼
        ┌────────────────────────────────────────────────────────────────┐
        │ Railway — FastAPI (main.py, 712 lines)                         │
        │  GET /api/health            liveness only                      │
        │  GET /api/tickers           504-row CSV dump                   │
        │  GET /api/research/{t}      full JSON (30-min TTLCache)        │
        │  GET /api/report/{t}/pdf    WeasyPrint PDF (deleted after send)│
        │  GET /api/prices/{t}        OHLCV for charts                   │
        │  GET /api/backtest          factor backtest                    │
        └───────┬────────────────────────────────────────────────────────┘
                ▼
   equity_research/
   ├── config.py / config.yaml      Rf 6.8%, ERP 5.5%, tax 25%, tg 4%
   ├── data/
   │   ├── yfinance_provider.py     single source, field-map normalisation,
   │   │                            USD→INR conversion, NO persistent cache
   │   └── nifty500_tickers.csv     504 tickers (ticker, name, sector, industry)
   ├── analysis/
   │   ├── router.py                characteristics-based decision tree
   │   ├── dcf.py                   SINGLE-stage FCFF DCF (flat growth, 5y)
   │   ├── residual_income.py       RI model (NI − Ke·BV)
   │   ├── excess_return.py         legacy bank model (mostly unused)
   │   ├── financial_sector.py      Justified P/B = (ROE−g)/(Ke−g) + bank metrics
   │   ├── sotp.py                  config-driven segments (RELIANCE, ITC, LT only)
   │   ├── comps.py / relative_valuation.py   peer multiples cross-check
   │   ├── india_valuation.py       PSU discount, group premium, promoter quality
   │   └── ratios.py                CFA ratio groups + CAGR
   ├── backtest/                    20-y factor backtest engine (IC analysis)
   └── report/
       ├── charts.py                2 PNG charts (price, revenue/margin)
       ├── builder.py               Jinja2 → WeasyPrint subprocess
       └── templates/report.html.j2 457-line single-CSS-block template
```

**Test suite:** 178 tests, all passing (verified 10 Jun 2026). Pure-math
functions are well covered; no live API calls in tests.

**Deployment:** Railway via nixpacks (pango/cairo correctly via nixPkgs),
`Procfile` single worker. Vercel frontend pointed at
`equity-research-api-production.up.railway.app`.

---

## 2. What Exists and Works

| Area | Status |
|---|---|
| FCFF DCF with WACC decomposition + sensitivity table | ✅ works, but single-stage |
| Rule-based router (7 rules, human-readable reasons) | ✅ works, characteristic-driven |
| Justified P/B for financials + NIM/GNPA/CASA metrics | ✅ works |
| SOTP for RELIANCE / ITC / LT | ✅ works (config-driven shares of EBITDA) |
| Residual income fallback for negative-FCFF industrials | ✅ works |
| Peer comps (P/E, EV/EBITDA, P/B, EV/Sales) | ✅ works |
| India adjustments (PSU discount, group premium, promoter, EQ) | ✅ works, proprietary differentiator |
| Broker consensus comparison | ✅ works |
| PDF generation via WeasyPrint subprocess | ✅ works on macOS + Railway |
| Frontend research dashboard with TradingView chart | ✅ works |
| Currency normalisation (INFY reports in USD) | ✅ handled |

## 3. What Is Broken / Missing / Weak

### Valuation engine (Phase 1 gaps)
- **Single-stage DCF**: flat growth for 5 years then terminal — no Stage-2 fade
  to terminal growth. Overvalues high-growth, undervalues fading businesses.
- **No size premium** in Ke; CAPM is `Rf + β·ERP` only.
- **Point-in-time capital structure** in WACC (spec: 3-year average D/E).
- **No DDM / H-Model** for banks (only Justified P/B).
- **No EV/GCI + ROIC-vs-WACC** (McKinsey value-driver) cross-check.
- **No primary + secondary blending** — exactly one model per company.
- **No bear/base/bull bands**, no target price, no BUY/HOLD/SELL rating.
- **No Valuation Confidence Score.**
- Beta is taken raw from yfinance with a silent default to 1.0 — no
  regression-based computation, no sector-median fallback.

### Financial analysis (Phase 2 — entirely absent)
- No Piotroski F-Score, Beneish M-Score, Altman Z-Score, Sloan accruals,
  DuPont 5-factor, Novy-Marx gross profitability, capital-allocation score,
  governance scorecard, or cash-conversion-cycle analysis.
- (india_valuation.py has a rudimentary CFO/EBITDA earnings-quality check —
  the only overlap.)

### Report design (Phase 3 — the "looks like ass" problem, confirmed)
- Single-column Arial document; h2s are navy bars but the page has **no cover
  page, no rating, no target price, no investment thesis**.
- Charts are low-DPI PNGs with inconsistent styling.
- No price-vs-benchmark chart, no DuPont/quality visuals, no scorecards.
- Business overview is an unedited yfinance paragraph dump.
- Verdict: looks like a homework printout, not a Kotak/Motilal Oswal note.

### Frontend (Phase 4 gaps)
- No ticker tape, no /universe browser, no /reports archive, no generation
  progress (PDF click just spins for 40 s), generic SaaS-dark aesthetic.

### Data infrastructure (Phase 5 gaps)
- No `company_universe.json` (CSV lacks valuation_family / mcap band / BSE code).
- Single data source (yfinance), no waterfall, no persistent cache (in-memory
  TTL only — every Railway restart re-fetches everything).
- No `ComputationResult` contract; failures handled ad-hoc per module.
- PDFs are deleted after download — no archive.

### Deployment (Phase 6 gaps)
- `/api/health` returns `{"status": "ok"}` only (spec: universe_size, cache_entries).
- `Procfile` runs one worker.

---

## 4. Prioritised Implementation Plan

Ordered by leverage (analyst-desk credibility per engineering hour):

1. **Phase 2 modules** (`analysis/quality.py`, `analysis/governance.py`) —
   pure-Python, unit-testable, feed both PDF and API. Includes the
   `ComputationResult` error contract (Phase 5.4) from day one.
2. **Phase 1 engine upgrades** — multi-stage DCF with linear fade (years 6–10),
   size premium + 3-y average D/E in WACC, regression beta w/ sector-median
   fallback, H-Model DDM for banks, ROIC-vs-WACC module, primary 60 / secondary
   40 blending, bear/base/bull bands, BUY/HOLD/SELL rating, Valuation
   Confidence Score (0–100).
3. **Phase 3 report rebuild** — new `report.html.j2` (IBM Plex, navy #0A2342
   palette, 7-page institutional layout), new SVG chart suite with a shared
   `research_style`, Piotroski scorecard, sensitivity heat map, confidence
   gauge, traffic-light governance table.
4. **Phase 5 data infra** — `data/company_universe.json` (all 504 constituents
   with valuation_family per sector router), JSON file cache (24 h prices /
   90 d financials) under `data/cache/` (`/tmp` on Railway), report archive
   index.
5. **Phase 4 frontend** — ticker tape (Nifty 50), `/universe` browser,
   `/reports` archive, SSE generation progress, navy re-skin.
6. **Phase 6** — `/health` with universe/cache stats, `tests/test_valuation.py`
   (10+ known-answer cases incl. negative-FCFF, sparse-data, bank edge cases),
   completion-criteria verification for RELIANCE / HDFCBANK / LT.

### Deliberate design decisions
- **Keep** the existing characteristics-based router rules as *overrides* on
  top of the new sector-family mapping: sector tells you the default model;
  observed financials (negative FCFF, missing operating income) can still
  re-route. This is strictly more auditable than either alone.
- **Keep** india_valuation.py and the backtest engine — genuine differentiators.
- **Replace** excess_return.py's role with the H-Model DDM path inside
  financial_sector.py (kept for backward compat until tests migrate).
- **Never delete** raw yfinance data on failure — every module returns a
  `ComputationResult` with warnings; the report renders "Data Not Available"
  sections rather than crashing.
- **Benchmark honesty**: Yahoo has no Nifty 50 TRI series; charts use ^NSEI
  (price index) and label it as such. Beta uses ^NSEI monthly returns with the
  limitation documented — this beats silently mislabelling a price index as TRI.
