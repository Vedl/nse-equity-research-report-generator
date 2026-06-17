"""Phase 3C — news sourcing, LM sentiment, and broker cross-check.

Google News RSS (free, no key) + Loughran-McDonald sentiment (pysentiment2).
Results are cached for 24 h per ticker so each deploy's lifetime only hits
the RSS feed once per name.

Discipline:
  - Sentiment is display context only.  It populates the overlay_notes in
    the recommendation but NEVER alters the intrinsic value, WACC/Ke, or
    the directional call.
  - Zero-LM-word headlines are neutral (Polarity=0), not an error.
  - Thin/empty/malformed feeds → limited_coverage=True; never fabricated.
  - The LM word lists that drove the score are surfaced for explainability.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Module-level conditional import so tests can patch ``_feedparser`` without
# feedparser being installed in the test environment (same pattern as pysentiment2).
try:
    import feedparser as _feedparser  # type: ignore[import-untyped]
except ImportError:
    _feedparser = None  # type: ignore[assignment]

_NEWS_TTL = 24 * 3600    # 24 h; matches cache.TTL_SECONDS["news"]
_MAX_HEADLINES = 10
_MIN_HEADLINES_FOR_SIGNAL = 3   # below this → limited_coverage

_GOOGLE_NEWS_TMPL = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NewsItem:
    title: str
    source: str
    published: str   # ISO-8601 date string "YYYY-MM-DD" or ""
    link: str        # canonical article link (for the JSON payload; not rendered in PDF)


@dataclass
class NewsSentimentResult:
    """News + LM-sentiment aggregate for one ticker.  Pure display context."""

    headlines: list[NewsItem]
    limited_coverage: bool

    # LM aggregate
    polarity: float | None           # (Pos−Neg)/(Pos+Neg); None when no LM words
    sentiment_label: str             # "Positive" / "Mildly positive" / "Neutral" /
                                     # "Mildly negative" / "Negative" / "No signal"
    pos_words: list[str]             # unique LM positive words that appeared
    neg_words: list[str]             # unique LM negative words that appeared
    carried_pct: float | None        # share of headlines that carried ≥1 LM word

    # reserved for future extension (LM.get_score does not return these for the
    # standard LM dictionary — kept as zero stubs for forward-compatibility)
    uncertainty_count: int = 0
    litigious_count: int = 0

    sourced_at: str = ""             # ISO-8601 UTC timestamp of the fetch


# ---------------------------------------------------------------------------
# RSS fetch
# ---------------------------------------------------------------------------


def _parse_published(entry: object) -> str:
    """Extract a YYYY-MM-DD date string from a feedparser entry."""
    import time as _time
    pt = getattr(entry, "published_parsed", None)
    if pt and isinstance(pt, _time.struct_time):
        return f"{pt.tm_year:04d}-{pt.tm_mon:02d}-{pt.tm_mday:02d}"
    return ""


def _google_news_rss(company_name: str) -> list[NewsItem]:
    """Fetch the Google News RSS for *company_name* and return deduplicated items."""
    if _feedparser is None:
        logger.warning("feedparser not installed; news sourcing unavailable")
        return []

    query = urllib.parse.quote_plus(f'"{company_name}" stock')
    url = _GOOGLE_NEWS_TMPL.format(query=query)
    try:
        feed = _feedparser.parse(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google News RSS fetch failed for %s: %s", company_name, exc)
        return []

    seen_titles: set[str] = set()
    items: list[NewsItem] = []
    for entry in feed.entries:
        title = (getattr(entry, "title", "") or "").strip()
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        source_obj = getattr(entry, "source", None)
        source = getattr(source_obj, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        published = _parse_published(entry)
        items.append(NewsItem(title=title, source=source, published=published, link=link))
        if len(items) >= _MAX_HEADLINES:
            break

    return items


# ---------------------------------------------------------------------------
# LM sentiment
# ---------------------------------------------------------------------------


def _lm_score(headlines: list[NewsItem]) -> dict:
    """Aggregate Loughran-McDonald sentiment across all headlines.

    Returns a dict with keys: polarity, pos_words, neg_words, carried_pct,
    uncertainty_count, litigious_count.
    Any ImportError → returns neutral-signal dict (graceful degradation).

    Implementation notes:
    - pysentiment2.LM().tokenize() uses nltk.regexp_tokenize (no punkt data needed)
      + Porter Stemmer (built-in). No external downloads required.
    - Word sets are _posset/_negset (stemmed lowercase strings).
    - get_score() returns numpy types; float()/int() are applied for serialisability.
    - Driving words: we match original (unstemmed, readable) words where their
      stemmed form appears in the LM word sets.
    """
    import re as _re

    empty: dict = {
        "polarity": None,
        "pos_words": [],
        "neg_words": [],
        "carried_pct": None,
        "uncertainty_count": 0,
        "litigious_count": 0,
    }
    if not headlines:
        return empty

    try:
        import pysentiment2 as ps  # type: ignore[import-untyped]
        lm = ps.LM()
    except ImportError:
        logger.warning("pysentiment2 not installed; sentiment scoring unavailable")
        return empty

    stemmer = lm._tokenizer._stemmer
    stopset = lm._tokenizer._stopset
    posset = lm._posset
    negset = lm._negset

    total_pos = 0
    total_neg = 0
    headlines_with_signal = 0
    all_pos_words: list[str] = []
    all_neg_words: list[str] = []

    for item in headlines:
        try:
            tokens = lm.tokenize(item.title)
            score = lm.get_score(tokens)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LM score failed for headline %r: %s", item.title[:60], exc)
            continue

        pos = int(score.get("Positive", 0))
        neg = int(score.get("Negative", 0))
        total_pos += pos
        total_neg += neg

        if pos > 0 or neg > 0:
            headlines_with_signal += 1

        # Extract human-readable (unstemmed) driving words by matching each raw
        # word's stemmed form against the LM word sets.
        for raw in _re.findall(r"[a-z]+", item.title.lower()):
            stemmed = stemmer.stem(raw)
            if stemmed in stopset:
                continue
            if stemmed in posset:
                all_pos_words.append(raw)
            if stemmed in negset:
                all_neg_words.append(raw)

    total_lm = total_pos + total_neg
    polarity: float | None = None
    if total_lm > 0:
        polarity = float((total_pos - total_neg) / total_lm)

    carried_pct = float(headlines_with_signal / len(headlines)) if headlines else None

    return {
        "polarity": polarity,
        "pos_words": _dedup_preserve_order(all_pos_words),
        "neg_words": _dedup_preserve_order(all_neg_words),
        "carried_pct": carried_pct,
        "uncertainty_count": 0,   # LM.get_score does not return Uncertainty
        "litigious_count": 0,
    }


def _dedup_preserve_order(words: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _sentiment_label(polarity: float | None, carried_pct: float | None) -> str:
    if polarity is None:
        return "No signal"
    if polarity >= 0.3:
        return "Positive"
    if polarity >= 0.05:
        return "Mildly positive"
    if polarity <= -0.3:
        return "Negative"
    if polarity <= -0.05:
        return "Mildly negative"
    return "Neutral"


# ---------------------------------------------------------------------------
# Cached entry point
# ---------------------------------------------------------------------------


def _cache_key(ticker: str) -> str:
    return f"{ticker}_news"


def get_news_sentiment(ticker: str, company_name: str) -> NewsSentimentResult:
    """Return cached (24 h) news+sentiment for *ticker*. Never raises."""
    from equity_research.data import cache as file_cache  # local import to avoid circularity

    key = _cache_key(ticker)
    cached = file_cache.get(key, "news")
    if cached is not None:
        try:
            return _deserialise(cached)
        except Exception as exc:  # noqa: BLE001
            logger.warning("News cache deserialise failed for %s: %s", ticker, exc)

    result = _fetch_and_score(company_name)
    try:
        file_cache.put(key, _serialise(result))
    except Exception as exc:  # noqa: BLE001
        logger.warning("News cache write failed for %s: %s", ticker, exc)
    return result


def _fetch_and_score(company_name: str) -> NewsSentimentResult:
    headlines = _google_news_rss(company_name)
    limited = len(headlines) < _MIN_HEADLINES_FOR_SIGNAL
    scored = _lm_score(headlines)
    label = _sentiment_label(scored["polarity"], scored["carried_pct"])
    sourced_at = _utc_now_iso()
    return NewsSentimentResult(
        headlines=headlines,
        limited_coverage=limited,
        polarity=scored["polarity"],
        sentiment_label=label,
        pos_words=scored["pos_words"],
        neg_words=scored["neg_words"],
        carried_pct=scored["carried_pct"],
        uncertainty_count=scored["uncertainty_count"],
        litigious_count=scored["litigious_count"],
        sourced_at=sourced_at,
    )


def _utc_now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Serialisation helpers (for the JSON file cache)
# ---------------------------------------------------------------------------


def _serialise(r: NewsSentimentResult) -> dict:
    return {
        "headlines": [
            {"title": h.title, "source": h.source, "published": h.published, "link": h.link}
            for h in r.headlines
        ],
        "limited_coverage": r.limited_coverage,
        "polarity": r.polarity,
        "sentiment_label": r.sentiment_label,
        "pos_words": r.pos_words,
        "neg_words": r.neg_words,
        "carried_pct": r.carried_pct,
        "uncertainty_count": r.uncertainty_count,
        "litigious_count": r.litigious_count,
        "sourced_at": r.sourced_at,
    }


def _deserialise(d: dict) -> NewsSentimentResult:
    return NewsSentimentResult(
        headlines=[
            NewsItem(
                title=h["title"], source=h["source"],
                published=h["published"], link=h["link"],
            )
            for h in d.get("headlines", [])
        ],
        limited_coverage=bool(d.get("limited_coverage", False)),
        polarity=d.get("polarity"),
        sentiment_label=str(d.get("sentiment_label", "No signal")),
        pos_words=list(d.get("pos_words", [])),
        neg_words=list(d.get("neg_words", [])),
        carried_pct=d.get("carried_pct"),
        uncertainty_count=int(d.get("uncertainty_count", 0)),
        litigious_count=int(d.get("litigious_count", 0)),
        sourced_at=str(d.get("sourced_at", "")),
    )
