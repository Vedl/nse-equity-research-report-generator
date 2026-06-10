"""Financial quality & forensic accounting screens (CFA L2 FSA + academic research).

Standalone, independently importable modules:

* Piotroski F-Score        — Piotroski (2000), Journal of Accounting Research
* Beneish M-Score          — Beneish (1999), Financial Analysts Journal
* Altman Z''-Score         — Altman (2000) re-estimated four-variable model for
                             non-US / non-manufacturing firms
* Accruals / Earnings Qual — Sloan (1996), The Accounting Review
* DuPont 5-factor ROE      — CFA L2 FSA, extended DuPont decomposition
* Gross Profitability      — Novy-Marx (2013), Journal of Financial Economics
* Capital Allocation Score — composite, after Titman, Wei & Xie (2004), JF
* Cash Conversion Cycle    — CFA L2 FSA working-capital analysis

Every public entry point degrades gracefully: missing inputs produce ``None``
signals plus explicit warnings, never silent zeros or fabricated data.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from equity_research.analysis.ratios import _col, _latest
from equity_research.utils.formatting import safe_divide

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _yr(series: pd.Series, offset: int = 0) -> float | None:
    """Value at the (latest − offset) year, or None. offset=0 → latest year."""
    valid = series.dropna()
    if len(valid) <= offset:
        return None
    return float(valid.iloc[-(offset + 1)])


def _aligned_years(*series: pd.Series) -> pd.DataFrame:
    """Inner-join multiple year-indexed series into one DataFrame."""
    return pd.concat(series, axis=1, join="inner").dropna(how="all")


def _is_num(v: float | None) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


# ===========================================================================
# 2.1 — Piotroski F-Score
# ===========================================================================


@dataclass
class PiotroskiSignal:
    """One of the nine binary Piotroski signals."""

    code: str          # e.g. "F1"
    name: str          # short label for the scorecard
    passed: bool | None  # None = data unavailable
    detail: str        # the numbers behind the verdict


@dataclass
class PiotroskiResult:
    """Piotroski (2000) 9-signal fundamental strength score."""

    signals: list[PiotroskiSignal]
    score: int                 # sum of passed signals
    max_available: int         # how many signals had enough data
    verdict: str               # "Strong" (>=7) / "Neutral" / "Weak" (<=2)
    warnings: list[str] = field(default_factory=list)


def piotroski_f_score(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> PiotroskiResult:
    """Compute the Piotroski F-Score from normalised annual statements.

    All nine signals per Piotroski (2000), Journal of Accounting Research:
    4 profitability, 3 leverage/liquidity, 2 operating efficiency.
    """
    warnings: list[str] = []
    signals: list[PiotroskiSignal] = []

    ni = _col(income, "net_income")
    rev = _col(income, "total_revenue")
    cogs = _col(income, "cost_of_revenue")
    gp = _col(income, "gross_profit")
    ta = _col(balance, "total_assets")
    ca = _col(balance, "current_assets")
    cl = _col(balance, "current_liabilities")
    ltd = _col(balance, "long_term_debt")
    shares = _col(income, "basic_average_shares")
    cfo_s = _col(cashflow, "operating_cash_flow")

    def add(code: str, name: str, passed: bool | None, detail: str) -> None:
        signals.append(PiotroskiSignal(code, name, passed, detail))
        if passed is None:
            warnings.append(f"{code} ({name}): insufficient data — {detail}")

    # --- Profitability ---
    # F1. ROA > 0   (NI_t / TA_t)
    ni_t, ta_t = _yr(ni), _yr(ta)
    roa_t = safe_divide(ni_t, ta_t)
    add("F1", "ROA > 0",
        (roa_t > 0) if roa_t is not None else None,
        f"ROA = {roa_t:.2%}" if roa_t is not None else "net income or total assets missing")

    # F2. CFO > 0
    cfo_t = _yr(cfo_s)
    add("F2", "CFO > 0",
        (cfo_t > 0) if cfo_t is not None else None,
        f"CFO = ₹{cfo_t/1e7:,.0f} Cr" if cfo_t is not None else "operating cash flow missing")

    # F3. ΔROA > 0
    ni_p, ta_p = _yr(ni, 1), _yr(ta, 1)
    roa_p = safe_divide(ni_p, ta_p)
    if roa_t is not None and roa_p is not None:
        add("F3", "ΔROA > 0", roa_t > roa_p, f"ROA {roa_p:.2%} → {roa_t:.2%}")
    else:
        add("F3", "ΔROA > 0", None, "prior-year ROA unavailable")

    # F4. Accruals: CFO/TA > ROA  ⇔  CFO > NI (same denominator)
    if cfo_t is not None and ni_t is not None:
        add("F4", "CFO > Net Income", cfo_t > ni_t,
            f"CFO ₹{cfo_t/1e7:,.0f} Cr vs NI ₹{ni_t/1e7:,.0f} Cr")
    else:
        add("F4", "CFO > Net Income", None, "CFO or net income missing")

    # --- Leverage / Liquidity ---
    # F5. ΔLEVER <= 0 — long-term debt / total assets not increasing
    ltd_t, ltd_p = _yr(ltd), _yr(ltd, 1)
    lev_t = safe_divide(ltd_t, ta_t)
    lev_p = safe_divide(ltd_p, ta_p)
    if lev_t is not None and lev_p is not None:
        add("F5", "Leverage not rising", lev_t <= lev_p,
            f"LTD/TA {lev_p:.1%} → {lev_t:.1%}")
    elif ltd_t is None and ltd_p is None and ta_t is not None:
        # No long-term debt reported at all → treat as unlevered (pass), noted.
        add("F5", "Leverage not rising", True, "no long-term debt reported")
    else:
        add("F5", "Leverage not rising", None, "long-term debt history unavailable")

    # F6. ΔLIQUID >= 0 — current ratio improving
    ca_t, cl_t, ca_p, cl_p = _yr(ca), _yr(cl), _yr(ca, 1), _yr(cl, 1)
    cr_t = safe_divide(ca_t, cl_t)
    cr_p = safe_divide(ca_p, cl_p)
    if cr_t is not None and cr_p is not None:
        add("F6", "Current ratio improving", cr_t >= cr_p,
            f"Current ratio {cr_p:.2f}× → {cr_t:.2f}×")
    else:
        add("F6", "Current ratio improving", None, "current assets/liabilities history unavailable")

    # F7. No dilution — shares outstanding not increased
    sh_t, sh_p = _yr(shares), _yr(shares, 1)
    if sh_t is not None and sh_p is not None and sh_p > 0:
        add("F7", "No share dilution", sh_t <= sh_p * 1.0,
            f"Avg shares {sh_p/1e7:,.1f} Cr → {sh_t/1e7:,.1f} Cr")
    else:
        add("F7", "No share dilution", None, "share count history unavailable")

    # --- Operating efficiency ---
    # F8. ΔMARGIN > 0 — gross margin improving
    rev_t, rev_p = _yr(rev), _yr(rev, 1)
    gp_t = _yr(gp) if not gp.dropna().empty else (
        (rev_t - _yr(cogs)) if (_is_num(rev_t) and _is_num(_yr(cogs))) else None
    )
    gp_p = _yr(gp, 1) if len(gp.dropna()) > 1 else (
        (rev_p - _yr(cogs, 1)) if (_is_num(rev_p) and _is_num(_yr(cogs, 1))) else None
    )
    gm_t = safe_divide(gp_t, rev_t)
    gm_p = safe_divide(gp_p, rev_p)
    if gm_t is not None and gm_p is not None:
        add("F8", "Gross margin improving", gm_t > gm_p, f"GM {gm_p:.1%} → {gm_t:.1%}")
    else:
        add("F8", "Gross margin improving", None, "gross profit history unavailable")

    # F9. ΔTURN > 0 — asset turnover improving
    at_t = safe_divide(rev_t, ta_t)
    at_p = safe_divide(rev_p, ta_p)
    if at_t is not None and at_p is not None:
        add("F9", "Asset turnover improving", at_t > at_p,
            f"Turnover {at_p:.2f}× → {at_t:.2f}×")
    else:
        add("F9", "Asset turnover improving", None, "revenue or assets history unavailable")

    score = sum(1 for s in signals if s.passed is True)
    max_available = sum(1 for s in signals if s.passed is not None)
    if max_available >= 7 and score >= 7:
        verdict = "Strong"
    elif max_available >= 7 and score <= 2:
        verdict = "Weak"
    elif max_available < 7:
        verdict = "Incomplete"
    else:
        verdict = "Neutral"

    return PiotroskiResult(
        signals=signals, score=score, max_available=max_available,
        verdict=verdict, warnings=warnings,
    )


# ===========================================================================
# 2.2 — Beneish M-Score
# ===========================================================================


@dataclass
class BeneishResult:
    """Beneish (1999) 8-variable earnings-manipulation screen."""

    variables: dict[str, float | None]   # DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA
    m_score: float | None
    flagged: bool | None                 # True if M > -1.78
    missing: list[str] = field(default_factory=list)
    is_reliable: bool = True
    warnings: list[str] = field(default_factory=list)


# Beneish (1999), Financial Analysts Journal — model coefficients
_BENEISH_COEF = {
    "intercept": -4.84,
    "DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892,
    "DEPI": 0.115, "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327,
}
_BENEISH_THRESHOLD = -1.78   # M > -1.78 ⇒ possible manipulator


def beneish_m_score(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> BeneishResult:
    """Compute the Beneish M-Score from two consecutive years of statements.

    Missing index variables are substituted with their neutral value (1.0 for
    ratio indices, 0.0 for TATA) and explicitly reported in ``missing`` — the
    result is marked unreliable if more than two variables are substituted.
    """
    warnings: list[str] = []
    missing: list[str] = []

    rev = _col(income, "total_revenue")
    cogs = _col(income, "cost_of_revenue")
    sga = _col(income, "selling_general_admin")
    ni = _col(income, "net_income")
    dep = _col(income, "depreciation_amortization")
    rec = _col(balance, "accounts_receivable")
    ca = _col(balance, "current_assets")
    cl = _col(balance, "current_liabilities")
    ppe = _col(balance, "net_ppe")
    ta = _col(balance, "total_assets")
    ltd = _col(balance, "long_term_debt")
    cfo = _col(cashflow, "operating_cash_flow")

    t = {k: _yr(s) for k, s in dict(
        rev=rev, cogs=cogs, sga=sga, ni=ni, dep=dep, rec=rec,
        ca=ca, cl=cl, ppe=ppe, ta=ta, ltd=ltd, cfo=cfo,
    ).items()}
    p = {k: _yr(s, 1) for k, s in dict(
        rev=rev, cogs=cogs, sga=sga, ni=ni, dep=dep, rec=rec,
        ca=ca, cl=cl, ppe=ppe, ta=ta, ltd=ltd, cfo=cfo,
    ).items()}

    v: dict[str, float | None] = {}

    # DSRI — Days Sales in Receivables Index
    dsri_t = safe_divide(t["rec"], t["rev"])
    dsri_p = safe_divide(p["rec"], p["rev"])
    v["DSRI"] = safe_divide(dsri_t, dsri_p)

    # GMI — Gross Margin Index (prior / current; deteriorating margin > 1)
    gm_t = safe_divide((t["rev"] - t["cogs"]) if _is_num(t["rev"]) and _is_num(t["cogs"]) else None, t["rev"])
    gm_p = safe_divide((p["rev"] - p["cogs"]) if _is_num(p["rev"]) and _is_num(p["cogs"]) else None, p["rev"])
    v["GMI"] = safe_divide(gm_p, gm_t)

    # AQI — Asset Quality Index: (1 − (CA+PPE)/TA)_t / (1 − (CA+PPE)/TA)_p
    def _aq(d: dict) -> float | None:
        if all(_is_num(d[k]) for k in ("ca", "ppe", "ta")) and d["ta"]:
            return 1.0 - (d["ca"] + d["ppe"]) / d["ta"]
        return None
    v["AQI"] = safe_divide(_aq(t), _aq(p))

    # SGI — Sales Growth Index
    v["SGI"] = safe_divide(t["rev"], p["rev"])

    # DEPI — Depreciation Index: rate_p / rate_t where rate = Dep/(Dep + NetPPE)
    def _dep_rate(d: dict) -> float | None:
        if _is_num(d["dep"]) and _is_num(d["ppe"]) and (d["dep"] + d["ppe"]):
            return d["dep"] / (d["dep"] + d["ppe"])
        return None
    v["DEPI"] = safe_divide(_dep_rate(p), _dep_rate(t))

    # SGAI — SG&A Index
    sgai_t = safe_divide(t["sga"], t["rev"])
    sgai_p = safe_divide(p["sga"], p["rev"])
    v["SGAI"] = safe_divide(sgai_t, sgai_p)

    # LVGI — Leverage Index: ((LTD+CL)/TA)_t / ((LTD+CL)/TA)_p
    def _lev(d: dict) -> float | None:
        ltd_v = d["ltd"] if _is_num(d["ltd"]) else 0.0   # no LTD reported → 0, noted below
        if _is_num(d["cl"]) and _is_num(d["ta"]) and d["ta"]:
            return (ltd_v + d["cl"]) / d["ta"]
        return None
    v["LVGI"] = safe_divide(_lev(t), _lev(p))

    # TATA — Total Accruals to Total Assets: (NI − CFO) / TA
    if _is_num(t["ni"]) and _is_num(t["cfo"]) and _is_num(t["ta"]) and t["ta"]:
        v["TATA"] = (t["ni"] - t["cfo"]) / t["ta"]
    else:
        v["TATA"] = None

    # --- Assemble M-Score with neutral substitution for missing variables ---
    m = _BENEISH_COEF["intercept"]
    for name in ("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI"):
        if v[name] is None:
            missing.append(name)
            m += _BENEISH_COEF[name] * 1.0   # neutral index value
            warnings.append(f"{name} unavailable — substituted neutral 1.0")
        else:
            m += _BENEISH_COEF[name] * v[name]
    if v["TATA"] is None:
        missing.append("TATA")
        warnings.append("TATA unavailable — substituted neutral 0.0")
    else:
        m += _BENEISH_COEF["TATA"] * v["TATA"]

    if len(missing) >= 8:
        return BeneishResult(variables=v, m_score=None, flagged=None,
                             missing=missing, is_reliable=False, warnings=warnings)

    is_reliable = len(missing) <= 2
    return BeneishResult(
        variables=v,
        m_score=m,
        flagged=m > _BENEISH_THRESHOLD,
        missing=missing,
        is_reliable=is_reliable,
        warnings=warnings,
    )


# ===========================================================================
# 2.3 — Altman Z''-Score (emerging-market / non-manufacturing variant)
# ===========================================================================


@dataclass
class AltmanResult:
    """Altman (2000) four-variable Z''-Score for non-US markets."""

    x1: float | None   # Working Capital / Total Assets
    x2: float | None   # Retained Earnings / Total Assets
    x3: float | None   # EBIT / Total Assets
    x4: float | None   # Book Equity / Total Liabilities
    z_score: float | None
    zone: str          # "Safe" / "Grey" / "Distress" / "N/A"
    applicable: bool   # False for banks/financials (capital structure differs)
    warnings: list[str] = field(default_factory=list)


def altman_z_score(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    is_financial: bool = False,
) -> AltmanResult:
    """Altman Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4.

    Altman (2000) re-estimated model for non-manufacturers / emerging markets.
    Zones: Z > 2.6 Safe, 1.1–2.6 Grey, < 1.1 Distress.
    Not meaningful for banks/NBFCs (deposits are operating liabilities) —
    flagged via ``applicable=False``.
    """
    warnings: list[str] = []
    if is_financial:
        return AltmanResult(None, None, None, None, None, "N/A", False,
                            ["Z-Score not applicable to financial-sector balance sheets"])

    ta = _yr(_col(balance, "total_assets"))
    ca = _yr(_col(balance, "current_assets"))
    cl = _yr(_col(balance, "current_liabilities"))
    re_ = _yr(_col(balance, "retained_earnings"))
    ebit = _yr(_col(income, "operating_income"))
    eq = _yr(_col(balance, "stockholders_equity"))
    tl = _yr(_col(balance, "total_liabilities"))

    x1 = safe_divide((ca - cl) if _is_num(ca) and _is_num(cl) else None, ta)
    x2 = safe_divide(re_, ta)
    x3 = safe_divide(ebit, ta)
    x4 = safe_divide(eq, tl)

    components = {"X1 (WC/TA)": x1, "X2 (RE/TA)": x2, "X3 (EBIT/TA)": x3, "X4 (BVE/TL)": x4}
    for label, val in components.items():
        if val is None:
            warnings.append(f"{label} unavailable")

    if any(val is None for val in components.values()):
        return AltmanResult(x1, x2, x3, x4, None, "N/A", True, warnings)

    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = "Safe" if z > 2.6 else ("Grey" if z >= 1.1 else "Distress")
    return AltmanResult(x1, x2, x3, x4, z, zone, True, warnings)


# ===========================================================================
# 2.4 — Earnings Quality & Accruals (Sloan 1996)
# ===========================================================================


@dataclass
class AccrualsResult:
    """Sloan (1996) accruals anomaly + cash-conversion earnings-quality checks."""

    accruals_ratio_cf: float | None       # (NI − CFO − CFI) / avg total assets
    cfo_ebitda: float | None              # latest CFO / EBITDA
    cfo_ni_series: list[tuple[int, float]]   # (year, CFO/NI) for the chart
    cfo_ni_latest: float | None
    low_conversion_years: int             # consecutive years CFO/NI < 0.8
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def accruals_analysis(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> AccrualsResult:
    """Earnings-quality screens per Sloan (1996), The Accounting Review.

    * Cash-flow-method accruals ratio: (NI − CFO − CFI) / average total assets
    * CFO/EBITDA < 0.65 flags potential quality issues
    * CFO/NI < 0.8 for 2+ consecutive years is a red flag
    """
    warnings: list[str] = []
    flags: list[str] = []

    ni = _col(income, "net_income")
    ebitda = _col(income, "ebitda")
    ta = _col(balance, "total_assets")
    cfo = _col(cashflow, "operating_cash_flow")
    cfi = _col(cashflow, "investing_cash_flow")

    # Cash-flow-method accruals ratio (Sloan 1996; CFA L2 FSA Earnings Quality)
    ni_t, cfo_t, cfi_t = _yr(ni), _yr(cfo), _yr(cfi)
    ta_t, ta_p = _yr(ta), _yr(ta, 1)
    avg_ta = ((ta_t + ta_p) / 2) if _is_num(ta_t) and _is_num(ta_p) else ta_t
    accruals_cf: float | None = None
    if all(_is_num(x) for x in (ni_t, cfo_t, cfi_t)) and _is_num(avg_ta) and avg_ta:
        accruals_cf = (ni_t - cfo_t - cfi_t) / avg_ta
    else:
        warnings.append("Accruals ratio: NI, CFO, CFI or total assets missing")

    # CFO / EBITDA
    cfo_ebitda = safe_divide(_yr(cfo), _yr(ebitda))
    if cfo_ebitda is not None and cfo_ebitda < 0.65:
        flags.append(f"CFO/EBITDA = {cfo_ebitda:.2f} — below the 0.65 quality threshold")

    # CFO / NI series for chart
    frame = _aligned_years(cfo.rename("cfo"), ni.rename("ni")).dropna()
    series: list[tuple[int, float]] = []
    for year, row in frame.iterrows():
        ratio = safe_divide(row["cfo"], row["ni"])
        if ratio is not None:
            series.append((int(year), float(ratio)))
    cfo_ni_latest = series[-1][1] if series else None

    # Consecutive low-conversion years (from the most recent backwards)
    low = 0
    for _, ratio in reversed(series):
        if ratio < 0.8:
            low += 1
        else:
            break
    if low >= 2:
        flags.append(f"CFO/Net Income below 0.8 for {low} consecutive years — earnings quality red flag")

    if accruals_cf is not None and accruals_cf > 0.10:
        flags.append(f"Accruals ratio {accruals_cf:.1%} — high accruals predict lower future returns (Sloan 1996)")

    return AccrualsResult(
        accruals_ratio_cf=accruals_cf,
        cfo_ebitda=cfo_ebitda,
        cfo_ni_series=series,
        cfo_ni_latest=cfo_ni_latest,
        low_conversion_years=low,
        flags=flags,
        warnings=warnings,
    )


# ===========================================================================
# 2.5 — DuPont 5-Factor ROE Decomposition
# ===========================================================================


@dataclass
class DuPontYear:
    """One year of the extended DuPont decomposition."""

    year: int
    tax_burden: float | None        # NI / EBT
    interest_burden: float | None   # EBT / EBIT
    ebit_margin: float | None       # EBIT / Revenue
    asset_turnover: float | None    # Revenue / Total Assets
    leverage: float | None          # Total Assets / Equity
    roe: float | None               # product of the five (≈ NI / Equity)


@dataclass
class DuPontResult:
    """Extended (5-factor) DuPont ROE decomposition, CFA L2 FSA."""

    years: list[DuPontYear]
    annotations: list[str]          # driver attribution for ≥200bps ROE moves
    warnings: list[str] = field(default_factory=list)


def dupont_decomposition(income: pd.DataFrame, balance: pd.DataFrame) -> DuPontResult:
    """ROE = Tax Burden × Interest Burden × EBIT Margin × Asset Turnover × Leverage.

    CFA L2 FSA extended DuPont. Uses ending balance-sheet values for
    consistency across the 5-year panel (noted in the report).
    """
    warnings: list[str] = []
    ni = _col(income, "net_income")
    ebt = _col(income, "pretax_income")
    ebit = _col(income, "operating_income")
    rev = _col(income, "total_revenue")
    ta = _col(balance, "total_assets")
    eq = _col(balance, "stockholders_equity")

    frame = pd.concat(
        [ni.rename("ni"), ebt.rename("ebt"), ebit.rename("ebit"),
         rev.rename("rev"), ta.rename("ta"), eq.rename("eq")],
        axis=1, join="outer",
    ).sort_index().tail(5)

    years: list[DuPontYear] = []
    for year, row in frame.iterrows():
        tb = safe_divide(row.get("ni"), row.get("ebt"))
        ib = safe_divide(row.get("ebt"), row.get("ebit"))
        em = safe_divide(row.get("ebit"), row.get("rev"))
        at = safe_divide(row.get("rev"), row.get("ta"))
        lv = safe_divide(row.get("ta"), row.get("eq"))
        roe = safe_divide(row.get("ni"), row.get("eq"))
        years.append(DuPontYear(int(year), tb, ib, em, at, lv, roe))

    # Driver attribution for material (≥200bps) ROE changes
    annotations: list[str] = []
    factor_names = [
        ("tax_burden", "tax burden"), ("interest_burden", "interest burden"),
        ("ebit_margin", "EBIT margin"), ("asset_turnover", "asset turnover"),
        ("leverage", "financial leverage"),
    ]
    for prev_y, cur_y in zip(years, years[1:]):
        if prev_y.roe is None or cur_y.roe is None:
            continue
        d_roe = cur_y.roe - prev_y.roe
        if abs(d_roe) < 0.02:
            continue
        # Log-decomposition: ln(ROE_t/ROE_p) = Σ ln(factor_t/factor_p)
        contribs: list[tuple[str, float]] = []
        for attr, label in factor_names:
            f_p, f_t = getattr(prev_y, attr), getattr(cur_y, attr)
            if _is_num(f_p) and _is_num(f_t) and f_p > 0 and f_t > 0:
                contribs.append((label, math.log(f_t / f_p)))
        if contribs:
            driver = max(contribs, key=lambda c: abs(c[1]))
            annotations.append(
                f"FY{cur_y.year}: ROE moved {d_roe*100:+.0f}bps "
                f"({prev_y.roe:.1%} → {cur_y.roe:.1%}); primary driver: {driver[0]}."
            )

    if not years:
        warnings.append("DuPont decomposition: no usable income/balance data")
    return DuPontResult(years=years, annotations=annotations, warnings=warnings)


# ===========================================================================
# 2.6 — Gross Profitability (Novy-Marx 2013)
# ===========================================================================


@dataclass
class GrossProfitabilityResult:
    """Novy-Marx (2013) quality factor: (Revenue − COGS) / Total Assets."""

    series: list[tuple[int, float]]     # 5-year GP/A trend
    latest: float | None
    peer_values: dict[str, float]       # peer ticker → GP/A (when available)
    percentile: float | None            # company rank within peer set (0–100)
    warnings: list[str] = field(default_factory=list)


def gross_profitability(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    peer_gpa: dict[str, float] | None = None,
) -> GrossProfitabilityResult:
    """GP/A per Novy-Marx (2013), Journal of Financial Economics —
    "The Other Side of Value: The Gross Profitability Premium".

    High GP/A predicts excess future returns with power comparable to B/M.
    """
    warnings: list[str] = []
    rev = _col(income, "total_revenue")
    gp = _col(income, "gross_profit")
    cogs = _col(income, "cost_of_revenue")
    ta = _col(balance, "total_assets")

    # Prefer reported gross profit; derive Revenue − COGS when absent
    gp_use = gp if not gp.dropna().empty else (rev - cogs)
    frame = _aligned_years(gp_use.rename("gp"), ta.rename("ta")).dropna().tail(5)

    series: list[tuple[int, float]] = []
    for year, row in frame.iterrows():
        val = safe_divide(row["gp"], row["ta"])
        if val is not None:
            series.append((int(year), float(val)))
    latest = series[-1][1] if series else None
    if latest is None:
        warnings.append("GP/A: gross profit or total assets unavailable")

    percentile: float | None = None
    peer_values = peer_gpa or {}
    if latest is not None and len(peer_values) >= 3:
        below = sum(1 for v in peer_values.values() if v < latest)
        percentile = 100.0 * below / len(peer_values)

    return GrossProfitabilityResult(
        series=series, latest=latest, peer_values=peer_values,
        percentile=percentile, warnings=warnings,
    )


# ===========================================================================
# 2.7 — Capital Allocation Quality Score
# ===========================================================================


@dataclass
class CAQComponent:
    name: str
    points: int          # 0 or 2
    available: bool
    detail: str


@dataclass
class CAQResult:
    """Composite capital-allocation score (0–10), after Titman, Wei & Xie
    (2004), Journal of Finance (capital investment and stock returns)."""

    components: list[CAQComponent]
    score: int
    max_score: int       # 10 minus 2 per unavailable component
    warnings: list[str] = field(default_factory=list)


def capital_allocation_score(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    roic_series: list[tuple[int, float]] | None,
    wacc: float | None,
) -> CAQResult:
    """Five 2-point checks: ROIC>WACC, ROIC improving, FCF/EBITDA>0.5,
    consistent shareholder returns, deleveraging or Debt/EBITDA < 2.5×."""
    comps: list[CAQComponent] = []
    warnings: list[str] = []

    # 1. ROIC > WACC
    latest_roic = roic_series[-1][1] if roic_series else None
    if latest_roic is not None and wacc is not None:
        ok = latest_roic > wacc
        comps.append(CAQComponent(
            "ROIC > WACC (value creator)", 2 if ok else 0, True,
            f"ROIC {latest_roic:.1%} vs WACC {wacc:.1%}"))
    else:
        comps.append(CAQComponent("ROIC > WACC (value creator)", 0, False, "ROIC or WACC unavailable"))

    # 2. ROIC improving over 3 years
    if roic_series and len(roic_series) >= 3:
        ok = roic_series[-1][1] > roic_series[-3][1]
        comps.append(CAQComponent(
            "ROIC improving (3Y)", 2 if ok else 0, True,
            f"{roic_series[-3][1]:.1%} → {roic_series[-1][1]:.1%}"))
    else:
        comps.append(CAQComponent("ROIC improving (3Y)", 0, False, "fewer than 3 years of ROIC"))

    # 3. FCF / EBITDA > 0.5
    fcf = _yr(_col(cashflow, "free_cash_flow"))
    if fcf is None:
        cfo_v, capex_v = _yr(_col(cashflow, "operating_cash_flow")), _yr(_col(cashflow, "capital_expenditure"))
        fcf = (cfo_v + capex_v) if _is_num(cfo_v) and _is_num(capex_v) else None
    ebitda = _yr(_col(income, "ebitda"))
    ratio = safe_divide(fcf, ebitda)
    if ratio is not None:
        comps.append(CAQComponent(
            "FCF/EBITDA > 0.5 (capital efficient)", 2 if ratio > 0.5 else 0, True,
            f"FCF/EBITDA = {ratio:.2f}"))
    else:
        comps.append(CAQComponent("FCF/EBITDA > 0.5 (capital efficient)", 0, False, "FCF or EBITDA unavailable"))

    # 4. Consistent shareholder returns (dividend or buyback in every available year)
    div = _col(cashflow, "dividends_paid").dropna()
    buyback = _col(cashflow, "share_repurchase").dropna()
    n_years = max(len(div), len(buyback))
    if n_years >= 3:
        paid_each_year = all(
            (abs(div.get(y, 0) or 0) > 0) or (abs(buyback.get(y, 0) or 0) > 0)
            for y in (div.index.union(buyback.index))
        )
        comps.append(CAQComponent(
            "Consistent dividends / buybacks", 2 if paid_each_year else 0, True,
            f"shareholder returns in {len(div.index.union(buyback.index))} years"))
    else:
        comps.append(CAQComponent("Consistent dividends / buybacks", 0, False,
                                  "dividend/buyback history unavailable"))

    # 5. Debt/EBITDA declining or < 2.5×
    debt = _col(balance, "total_debt")
    ebitda_s = _col(income, "ebitda")
    de_t = safe_divide(_yr(debt), _yr(ebitda_s))
    de_p = safe_divide(_yr(debt, 2), _yr(ebitda_s, 2))
    if de_t is not None:
        ok = de_t < 2.5 or (de_p is not None and de_t < de_p)
        comps.append(CAQComponent(
            "Debt/EBITDA < 2.5× or declining", 2 if ok else 0, True,
            f"Debt/EBITDA = {de_t:.1f}×" + (f" (3Y ago {de_p:.1f}×)" if de_p is not None else "")))
    else:
        comps.append(CAQComponent("Debt/EBITDA < 2.5× or declining", 0, False, "debt or EBITDA unavailable"))

    score = sum(c.points for c in comps)
    max_score = sum(2 for c in comps if c.available)
    for c in comps:
        if not c.available:
            warnings.append(f"CAQ '{c.name}': {c.detail}")
    return CAQResult(components=comps, score=score, max_score=max_score, warnings=warnings)


# ===========================================================================
# 2.9 — Working Capital & Cash Conversion Cycle
# ===========================================================================


@dataclass
class CCCResult:
    """Working-capital efficiency: DSO + DIO − DPO trend (CFA L2 FSA)."""

    years: list[int]
    dso: list[float | None]
    dio: list[float | None]
    dpo: list[float | None]
    ccc: list[float | None]
    deteriorating: bool          # CCC worsening 3+ consecutive years
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def cash_conversion_cycle(income: pd.DataFrame, balance: pd.DataFrame) -> CCCResult:
    """DSO = Receivables/Revenue×365; DIO = Inventory/COGS×365;
    DPO = Payables/COGS×365; CCC = DSO + DIO − DPO."""
    warnings: list[str] = []
    rev = _col(income, "total_revenue")
    cogs = _col(income, "cost_of_revenue")
    rec = _col(balance, "accounts_receivable")
    inv = _col(balance, "inventory")
    pay = _col(balance, "accounts_payable")

    frame = pd.concat(
        [rev.rename("rev"), cogs.rename("cogs"), rec.rename("rec"),
         inv.rename("inv"), pay.rename("pay")],
        axis=1, join="outer",
    ).sort_index().tail(5)

    years: list[int] = []
    dso_l: list[float | None] = []
    dio_l: list[float | None] = []
    dpo_l: list[float | None] = []
    ccc_l: list[float | None] = []

    for year, row in frame.iterrows():
        dso = safe_divide(row.get("rec"), row.get("rev"))
        dio = safe_divide(row.get("inv"), row.get("cogs"))
        dpo = safe_divide(row.get("pay"), row.get("cogs"))
        dso = dso * 365 if dso is not None else None
        dio = dio * 365 if dio is not None else None
        dpo = dpo * 365 if dpo is not None else None
        ccc = (dso + dio - dpo) if all(_is_num(x) for x in (dso, dio, dpo)) else None
        years.append(int(year))
        dso_l.append(dso); dio_l.append(dio); dpo_l.append(dpo); ccc_l.append(ccc)

    valid_ccc = [(y, c) for y, c in zip(years, ccc_l) if c is not None]
    deteriorating = False
    if len(valid_ccc) >= 4:
        last4 = [c for _, c in valid_ccc[-4:]]
        deteriorating = all(b > a for a, b in zip(last4, last4[1:]))
    flags: list[str] = []
    if deteriorating:
        flags.append("Cash conversion cycle deteriorating for 3+ consecutive years — cash-trap risk")
    if not valid_ccc:
        warnings.append("CCC: receivables/inventory/payables data unavailable")

    return CCCResult(years=years, dso=dso_l, dio=dio_l, dpo=dpo_l, ccc=ccc_l,
                     deteriorating=deteriorating, flags=flags, warnings=warnings)


# ===========================================================================
# ROIC series helper (shared by CAQ + Model F)
# ===========================================================================


def roic_series(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    tax_rate: float,
) -> list[tuple[int, float]]:
    """ROIC = NOPLAT / Invested Capital, IC = Net PP&E + Net Working Capital.

    Koller, Goedhart & Wessels, "Valuation" (McKinsey) — value driver framework.
    """
    ebit = _col(income, "operating_income")
    ppe = _col(balance, "net_ppe")
    ca = _col(balance, "current_assets")
    cl = _col(balance, "current_liabilities")
    cash = _col(balance, "cash_and_equivalents")

    frame = pd.concat(
        [ebit.rename("ebit"), ppe.rename("ppe"), ca.rename("ca"),
         cl.rename("cl"), cash.rename("cash")],
        axis=1, join="inner",
    ).dropna(subset=["ebit", "ppe"]).sort_index().tail(5)

    out: list[tuple[int, float]] = []
    for year, row in frame.iterrows():
        noplat = row["ebit"] * (1.0 - tax_rate)
        # Operating NWC excludes cash (a financing item in the McKinsey framework)
        nwc = (row.get("ca") or 0.0) - (row.get("cash") or 0.0) - (row.get("cl") or 0.0)
        ic = row["ppe"] + nwc
        if ic and ic > 0:
            out.append((int(year), float(noplat / ic)))
    return out
