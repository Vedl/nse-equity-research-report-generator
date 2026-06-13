"""Regression test for BUG 2 — server-side PDF generation must produce a valid PDF.

The report template must render fully offline (no remote font @import), so PDF
generation never stalls on outbound HTTPS inside the WeasyPrint subprocess.

If the WeasyPrint system libraries (pango / cairo / gdk-pixbuf) are not present
in the test environment, ``generate_report`` falls back to writing HTML; in that
case the test is skipped rather than failed, since the libraries are an
environment dependency (installed via the Dockerfile on Railway).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from equity_research.config import load_config
from equity_research.report.builder import generate_report

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


class _OfflineProvider:
    """DataProvider stub for the report builder — no network access."""

    def __init__(self, profile: dict, financials: dict[str, pd.DataFrame]) -> None:
        self._profile = profile
        self._financials = financials

    def get_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        return pd.DataFrame()  # empty → charts render a "no data" placeholder

    def get_peers(self, ticker: str) -> list[str]:
        return []

    def get_profile(self, ticker: str) -> dict:
        return self._profile

    def get_financials(self, ticker: str) -> dict[str, pd.DataFrame]:
        return self._financials


def test_generate_report_produces_valid_pdf(
    cfg,
    tmp_path,
    monkeypatch,
    synthetic_profile,
    synthetic_income,
    synthetic_balance,
    synthetic_cashflow,
):
    """generate_report() must emit a non-empty, valid PDF for a single company."""
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path))

    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    provider = _OfflineProvider(synthetic_profile, financials)

    out = generate_report("TESTCORP.NS", provider, cfg)

    if out.suffix == ".html":
        pytest.skip(
            "WeasyPrint system libraries unavailable — generation fell back to HTML "
            "(install libpango/libcairo/libgdk-pixbuf; on Railway via the Dockerfile)."
        )

    assert out.suffix == ".pdf"
    data = out.read_bytes()
    assert data[:5] == b"%PDF-", "output is not a valid PDF (missing %PDF- header)"
    assert len(data) > 1_000, "PDF is suspiciously small / empty"


def test_report_template_has_no_remote_font_import():
    """The template must not @import remote fonts — that made PDF render network-bound."""
    template = (
        _REPO / "equity_research" / "report" / "templates" / "report.html.j2"
    ).read_text()
    assert "fonts.googleapis.com" not in template
    assert "@import url('http" not in template and '@import url("http' not in template
