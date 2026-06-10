# NSE Research Engine — Equity Research Report Generator

Generates a CFA-aligned, institutional-grade, 7-page PDF equity research report
for any Nifty 500 company from a single ticker input — multi-model intrinsic
valuation, forensic accounting screens, a rated 12-month target, and a
Kotak/Motilal-style layout rendered with WeasyPrint.

```
python -m equity_research RELIANCE
# → reports/RELIANCE_equity_research_YYYYMMDD.pdf
```

---

## What's in a report

| Page | Content |
|---|---|
| 1 — Cover | Navy masthead, **BUY/HOLD/SELL** rating pill, CMP, 12-month target, upside, investment thesis, key statistics |
| 2 — Executive Summary | Bear/base/bull band, 60/40 model blend, price vs Nifty 50 (indexed), **Valuation Confidence Score** gauge (0–100), DCF sensitivity heat map |
| 3 — Financial Summary | 5-year history + 2-year estimates (E): Revenue, EBITDA, EBIT, PAT, EPS, DPS, CFO, CapEx, FCFF, Net debt/EBITDA, RoE, RoIC + charts; bank analytics for financials |
| 4 — DuPont & Quality | 5-factor DuPont with driver attribution, **Piotroski F-Score** 9-signal scorecard, earnings quality (Sloan accruals, CFO/NI), cash conversion cycle, **ROIC vs WACC**, Capital Allocation Quality, Novy-Marx GP/A |
| 5 — Comps | Peer multiples with median + premium/discount note, implied values, SOTP segment table for conglomerates, India valuation engine adjustments |
| 6 — Risk & Governance | **Beneish M-Score** banner (flag/clean), Altman Z″-Score zone, promoter/governance traffic lights, numbered risk factors |
| 7 — Appendix | Full P&L / balance sheet / cash flow (5Y, ₹ Cr, Indian digit grouping) + every model assumption with its source |

## Valuation engine (rule-based, no ML — fully auditable)

The sector router assigns a primary model per company
(`data/company_universe.json` carries the family for all 504 constituents):

| Family | Primary model |
|---|---|
| Banks / NBFCs / Insurance | Justified P/B `(ROE−g)/(Ke−g)` blended 50/50 with H-Model DDM |
| Conglomerates (RELIANCE, ITC, LT) | Sum-of-the-Parts with segment multiples |
| Metals, Real Estate, Oil & Gas | EV/EBITDA peer comps |
| IT, Pharma, FMCG, default | **Two-stage FCFF DCF** — 5 years at g₁, 5-year linear fade to terminal growth |

Observed financials can still re-route (negative EBITDA → EV/Sales, negative
median FCFF → Residual Income, etc.).

Engine upgrades over a plain DCF:
- **Ke = Rf + β·ERP + α_size** — size premium 0.5%/1.0%/2.0% by cap band; β from a
  60-month monthly OLS regression vs ^NSEI with sector-median fallback (<24 months)
- 3-year average debt in WACC weights (no point-in-time distortion)
- Primary 60% / secondary 40% blend (FCFF's secondary is Residual Income);
  India engine adjustments (PSU discount, promoter quality) applied on top
- **Valuation Confidence Score** (0–100): model agreement, data depth, peer
  count, beta quality, consensus availability, earnings quality, minus
  penalties for negative FCFF / high accruals / Beneish flag
- Rating bands: BUY ≥ +15% · HOLD −10%…+15% · SELL < −10%

## Forensic quality screens (`equity_research/analysis/quality.py`)

Each module is independently importable and cites its source paper:
Piotroski (2000) F-Score · Beneish (1999) M-Score · Altman (2000) Z″ ·
Sloan (1996) accruals · CFA L2 5-factor DuPont · Novy-Marx (2013) gross
profitability · capital-allocation composite (Titman, Wei & Xie 2004) ·
working-capital/CCC analysis · promoter & governance scorecard.

**No hallucinated data**: anything unavailable from the automated pipeline
(GNPA, pledge %, board independence…) renders as N/A — never estimated.

## API (FastAPI)

| Endpoint | Purpose |
|---|---|
| `GET /health` | `{status, universe_size, cache_entries}` |
| `GET /api/research/{ticker}` | Full JSON: valuation + conviction + all quality screens |
| `GET /api/report/{ticker}/pdf` | Generate + download the PDF |
| `GET /api/report/{ticker}/stream` | **SSE** progress events for the live tracker |
| `GET /api/reports` / `/api/reports/file/{name}` | Archive index / re-download |
| `GET /api/universe` | 504 companies with valuation family + data status |
| `GET /api/indices` | Nifty levels for the frontend ticker tape |
| `GET /api/backtest` | 20-year factor backtest (IC analysis) |

## Frontend (Next.js 14, Vercel)

Live ticker tape (Nifty 50/500) on every page · `/universe` browser with
family/sector filters and data-status badges · `/reports` archive with rating
badges and re-download · research dashboard with SSE generation progress and
inline PDF preview.

## Setup

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
brew install pango            # macOS; Linux: libpango-1.0-0 libcairo2 libgdk-pixbuf2.0-0

python -m equity_research HDFCBANK            # CLI
uvicorn main:app --reload                     # API
cd frontend && npm i && npm run dev           # frontend (Node ≥ 18)
```

Config lives in `config.yaml`; `INDIA_ERP`, `RISK_FREE_RATE`,
`REPORT_OUTPUT_DIR`, `CACHE_DIR`, `ALLOWED_ORIGINS` env vars override at
deploy time (see `.env.example`). Market data is disk-cached
(`data/cache/`, 24 h prices / 90 d financials).

## Tests

```bash
pytest tests/ -v   # 202 tests — every valuation formula has a known-answer case
```

Includes the edge-case suite: all-negative FCFF, negative-equity bank,
<3 years of data, Piotroski strong-vs-weak, Beneish manipulator-profile
flagging, H-Model boundary conditions, Indian digit grouping.

## Data sources & honest limitations

- **yfinance** primary (disk-cached); peer multiples are plausibility-filtered
  (EV/EBITDA > 100× etc. treated as missing — Yahoo currency mismatches).
- Yahoo carries **no Nifty TRI series** — beta and relative-performance use
  ^NSEI (price index) and the report says so.
- Bank regulatory metrics (GNPA, PCR, CASA, CRAR) and BSE-filing governance
  fields are N/A by design rather than scraped unreliably.
- This report is **not investment advice**; all outputs are educational.

## Why I built this

To embed CFA Level II valuation and FSA directly into code — model routing,
two-stage DCF mechanics, residual income, justified multiples, forensic
screens — and to prove the India-specific structural factors (PSU discount,
group premium) with a 20-year factor backtest rather than asserting them.
