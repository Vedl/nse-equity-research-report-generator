# Project: Equity Research Report Generator

## What this is
A Python tool that generates an equity research report for any Nifty 500 company
from a single ticker input. Output is a formatted multi-page PDF.

## Conventions
- Python 3.11+. Use a virtual env. Manage deps with pip + requirements.txt (keep deps minimal).
- Format with ruff/black. Type hints on all public functions. Docstrings on modules and public functions.
- Tests with pytest. Every valuation/math function must have unit tests with known-answer cases.
- Config-driven, not hardcoded: risk-free rate, equity risk premium, tax rate, terminal growth,
  projection horizon all live in a config file (config.yaml), never as magic numbers in code.
- Indian-market specifics: NSE tickers use the `.NS` suffix; currency is INR.

## Hard rules
- NEVER fabricate financial data. If a data field is missing/None from the provider, surface it
  explicitly (log a warning, mark "n/a" in the report) — do not invent or silently default it.
- DCF assumptions are illustrative, analyst-adjustable inputs, not "answers." Always print every
  assumption used and include a sensitivity table. The report carries a "not investment advice" note.
- Abstract the data source behind an interface so providers can be swapped later.

## Workflow
- Plan before building. Build milestone by milestone (see plan). After each milestone: run tests,
  give a 2-line summary, and commit with a clear message. Ask before adding heavy dependencies or
  making irreversible structural choices.
