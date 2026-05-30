---
Project: Equity Research Report Generator
Language: Python 3.11+. Virtual env. pip + requirements.txt with pinned versions.
Style: ruff/black formatting. Type hints on all public functions. Docstrings on modules and classes.
Tests: pytest. Every valuation/math function needs unit tests with known-answer inputs.
Config: all assumptions (risk-free rate, ERP, tax rate, terminal growth, projection horizon)
live in config.yaml — never hardcoded.
India specifics: NSE tickers use .NS suffix. Currency INR. Tax rate ~25%.
Rules:
- NEVER fabricate or default financial data. If a field is missing from yfinance, log a warning
  and mark it as unavailable in the output — do not invent it.
- DCF assumptions are analyst inputs, not magic answers. Every assumption used must be printed
  and included in the PDF appendix. Sensitivity table mandatory.
- The FastAPI layer must have CORS configured to allow the frontend origin.
---
