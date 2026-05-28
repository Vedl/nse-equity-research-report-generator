# Equity Research Report Generator

Generates a CFA-aligned, multi-page PDF equity research report for any Nifty 500 company from a single ticker input.

```
python -m equity_research RELIANCE
# → reports/RELIANCE_equity_research_20260529.pdf  (≈ 200 KB)
```

---

## What's in the report

| Section | Content |
|---|---|
| Company Snapshot | Name, sector, price, market cap, 52W range, beta, P/E, P/B, dividend yield |
| Business Overview | Company description (from yfinance) |
| Financial Summary | 4-year income statement, balance sheet, and cash flow highlights |
| Ratio Analysis | Profitability, liquidity, solvency, efficiency (CFA-style grouping), revenue & EPS CAGR |
| DCF Valuation | WACC decomposition, 5-year FCFF projection, Gordon-growth terminal value, EV bridge, 5×5 WACC × terminal-growth sensitivity table |
| Comparable Companies | Peer P/E, EV/EBITDA, P/B, EV/Sales — median multiples → implied value range |
| Valuation Summary | DCF and comps range vs current price, upside / (downside) % |
| Charts | Price history with 52W band; revenue and margin trend |
| Assumptions Appendix | Every config input used in the analysis |
| Disclaimer | "Not investment advice" |

---

## Requirements

- **Python 3.11+**
- **macOS**: Homebrew + `pango` for WeasyPrint PDF rendering
- **Linux**: `libpango-1.0-0 libcairo2 libgdk-pixbuf2.0-0` (system packages)

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd "Equity Research Report Generator"
python3.11 -m venv venv
source venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install system library for PDF rendering (macOS)

```bash
brew install pango
```

> **Linux (Debian/Ubuntu)**
> ```bash
> sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libffi-dev
> ```

WeasyPrint automatically finds the Homebrew libraries; the builder sets `DYLD_LIBRARY_PATH` in the subprocess it spawns.

---

## Usage

```bash
# Activate venv first
source venv/bin/activate

# Generate a report (writes to ./reports/)
python -m equity_research RELIANCE

# With .NS suffix — same result
python -m equity_research RELIANCE.NS

# Custom output directory
python -m equity_research HDFCBANK --output ~/Desktop

# Use a different config file
python -m equity_research INFY --config my_config.yaml

# Dry run — print normalized data without generating a PDF
python -m equity_research TATAMOTORS --dry-run
```

Output file: `{output_dir}/{TICKER}_equity_research_{YYYYMMDD}.pdf`

---

## Configuration (`config.yaml`)

All valuation assumptions live here — never in code.

```yaml
market:
  risk_free_rate: 0.068        # 10Y G-Sec yield
  equity_risk_premium: 0.055   # Damodaran India ERP
  tax_rate: 0.25               # Corporate tax rate

dcf:
  projection_horizon: 5        # years of explicit FCFF projection
  terminal_growth_rate: 0.04   # Gordon-growth perpetuity rate
  revenue_growth_source: historical_cagr   # or "manual"
  # revenue_growth_override: 0.12          # uncomment for manual rate

peers:
  max_peers: 5
  # overrides:                             # hardcode peers per ticker
  #   RELIANCE: [ONGC.NS, IOC.NS, BPCL.NS]

report:
  currency: INR
  output_dir: ./reports
  charts:
    price_history_period: 2y
    figsize: [10, 4]
```

To override peers for a specific ticker, add entries under `peers.overrides`.  
To use a fixed growth rate for the DCF projection, set `revenue_growth_source: manual` and uncomment `revenue_growth_override`.

---

## Running tests

```bash
pytest tests/ -v
# 165 tests, all passing
```

Tests cover every valuation math function with hand-computed known-answer cases. No live API calls in the test suite — all DataProvider calls are mocked.

---

## Project structure

```
equity_research/
├── __main__.py            # CLI entry point
├── config.py              # Typed AppConfig dataclasses, loads config.yaml
├── data/
│   ├── provider.py        # DataProvider ABC
│   ├── yfinance_provider.py   # YFinanceProvider implementation
│   └── nifty500_tickers.csv   # Bundled peer-selection universe
├── analysis/
│   ├── ratios.py          # CFA ratio groups + CAGR
│   ├── dcf.py             # WACC, FCFF projection, TV, sensitivity table
│   ├── comps.py           # Peer multiples → implied value range
│   └── valuation.py       # Blended summary + upside/downside
└── report/
    ├── charts.py          # matplotlib: price history, revenue & margin
    ├── builder.py         # Full pipeline → PDF via WeasyPrint subprocess
    └── templates/
        └── report.html.j2 # Jinja2 A4 HTML template with inline CSS
config.yaml
requirements.txt
tests/
```

---

## Data source & known limitations

Data comes from **yfinance** (Yahoo Finance). Limitations:

- **Missing fields**: Some NSE tickers (especially smaller caps) return sparse `info` dicts. All missing fields are logged as `WARNING` and shown as `n/a` in the report — never silently defaulted or fabricated.
- **EPS**: `basic_eps` is often `0` or missing for Indian stocks in yfinance. The comps module falls back to `trailingEps` from the info dict, then to `net_income / shares`.
- **Peer multiples** (`enterprise_to_ebitda`, `enterprise_to_revenue`): Not always populated for NSE-listed peers. Peers with no usable multiples are skipped with a warning.
- **Temporary 404s**: yfinance occasionally returns 404 for valid tickers (rate limiting or data delays). The report generates with available data; re-run after a few minutes.
- **DCF accuracy**: Assumptions are illustrative analyst inputs. The sensitivity table is included specifically to convey the range of outcomes. This report is **not investment advice**.

To swap the data source, implement the `DataProvider` interface in `equity_research/data/provider.py` and pass your implementation to `generate_report()`.

---

## Disclaimer

This tool is for informational and educational purposes only. All outputs are based on publicly available data and analyst-adjustable assumptions. **This is not investment advice.** Past performance is not indicative of future results.
