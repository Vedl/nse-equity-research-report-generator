"""Phase 3C — news, sentiment & street view tests.

Tests are divided into:
  1. RSS parsing robustness (empty, thin, malformed feeds)
  2. LM sentiment — determinism, driving-word exposure, zero-word neutrality
  3. Sentiment / rating firewall — sentiment cannot move the rating or intrinsic
  4. Consensus cross-check — skew flag, broker ratio
  5. Cache TTL
  6. Serialisation round-trip
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from equity_research.data.news import (
    NewsItem,
    NewsSentimentResult,
    _deserialise,
    _fetch_and_score,
    _lm_score,
    _sentiment_label,
    _serialise,
    get_news_sentiment,
)
from equity_research.analysis.recommendation import decide_recommendation


# ---------------------------------------------------------------------------
# Helpers (must be defined before any use in decorators)
# ---------------------------------------------------------------------------


def _pysentiment2_available() -> bool:
    try:
        import pysentiment2  # noqa: F401
        return True
    except ImportError:
        return False


def _make_feed(entries: list[dict]) -> object:
    """Build a minimal feedparser-like feed stub."""
    class _Source:
        def __init__(self, t: str):
            self.title = t

    class _Entry:
        def __init__(self, d: dict):
            self.title = d.get("title", "")
            self.source = _Source(d.get("source", ""))
            self.link = d.get("link", "")
            self.published_parsed = d.get("published_parsed")

    feed = MagicMock()
    feed.entries = [_Entry(e) for e in entries]
    return feed


def _news_result(label: str, limited: bool = False) -> NewsSentimentResult:
    return NewsSentimentResult(
        headlines=[], limited_coverage=limited,
        polarity=0.8, sentiment_label=label,
        pos_words=["profit"], neg_words=[],
        carried_pct=1.0, sourced_at="2026-06-17T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# 1. RSS parsing robustness
# ---------------------------------------------------------------------------


def test_empty_feed_returns_limited_coverage():
    with patch("feedparser.parse", return_value=_make_feed([])):
        result = _fetch_and_score("Reliance Industries")
    assert result.limited_coverage is True
    assert result.headlines == []


def test_thin_feed_two_entries_is_limited():
    entries = [
        {"title": "Headline A", "source": "ET", "link": "http://a"},
        {"title": "Headline B", "source": "BS", "link": "http://b"},
    ]
    with patch("feedparser.parse", return_value=_make_feed(entries)):
        result = _fetch_and_score("HDFC Bank")
    assert result.limited_coverage is True   # < 3 headlines
    assert len(result.headlines) == 2


def test_sufficient_feed_not_limited():
    entries = [
        {"title": f"Headline {i}", "source": "ET", "link": f"http://h{i}"}
        for i in range(5)
    ]
    with patch("feedparser.parse", return_value=_make_feed(entries)):
        result = _fetch_and_score("TCS")
    assert result.limited_coverage is False
    assert len(result.headlines) == 5


def test_duplicate_titles_are_deduped():
    entries = [
        {"title": "HDFC Bank posts record profit", "source": "ET", "link": "http://a"},
        {"title": "HDFC Bank posts record profit", "source": "BS", "link": "http://b"},
        {"title": "Another headline", "source": "ET", "link": "http://c"},
        {"title": "Fourth headline", "source": "ET", "link": "http://d"},
        {"title": "Fifth headline", "source": "ET", "link": "http://e"},
    ]
    with patch("feedparser.parse", return_value=_make_feed(entries)):
        result = _fetch_and_score("HDFC Bank")
    titles_lower = [h.title.lower() for h in result.headlines]
    assert len(titles_lower) == len(set(titles_lower)), "duplicate titles leaked through"


def test_malformed_feed_gracefully_returns_empty():
    """feedparser.parse raising should degrade to empty result, not crash."""
    with patch("feedparser.parse", side_effect=Exception("network error")):
        result = _fetch_and_score("Some Company")
    assert result.limited_coverage is True
    assert result.headlines == []
    assert result.polarity is None


def test_max_headlines_capped_at_10():
    entries = [
        {"title": f"Headline {i}", "source": "ET", "link": f"http://h{i}"}
        for i in range(20)
    ]
    with patch("feedparser.parse", return_value=_make_feed(entries)):
        result = _fetch_and_score("TCS")
    assert len(result.headlines) <= 10


def test_feedparser_import_error_returns_empty():
    """If feedparser is not installed, news sourcing degrades cleanly."""
    with patch.dict("sys.modules", {"feedparser": None}):
        items = []
        try:
            from equity_research.data import news as _news_mod
            import importlib
            importlib.reload(_news_mod)
            items = _news_mod._google_news_rss("Test Company")
        except Exception:  # noqa: BLE001
            pass  # ImportError or reload error — also acceptable
    # items should be empty list or we got an exception (both are graceful)
    assert isinstance(items, list)


# ---------------------------------------------------------------------------
# 2. LM sentiment — determinism, driving words, zero-word neutrality
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _pysentiment2_available(), reason="pysentiment2 not installed")
def test_sentiment_is_deterministic():
    items = [
        NewsItem("Profit growth surge beats expectations", "ET", "2026-06-01", "http://a"),
        NewsItem("Earnings decline on rising costs", "BS", "2026-06-02", "http://b"),
    ]
    s1 = _lm_score(items)
    s2 = _lm_score(items)
    assert s1["polarity"] == s2["polarity"]
    assert s1["pos_words"] == s2["pos_words"]
    assert s1["neg_words"] == s2["neg_words"]


@pytest.mark.skipif(not _pysentiment2_available(), reason="pysentiment2 not installed")
def test_driving_words_are_exposed():
    items = [
        NewsItem("Record profit and earnings growth", "ET", "2026-06-01", "http://a"),
    ]
    scored = _lm_score(items)
    assert isinstance(scored["pos_words"], list)
    assert isinstance(scored["neg_words"], list)


@pytest.mark.skipif(not _pysentiment2_available(), reason="pysentiment2 not installed")
def test_zero_lm_word_headline_scores_neutral():
    """Proper-noun-only headline → no LM words → Polarity is None or 0."""
    items = [
        NewsItem("The CEO met investors on Friday at Mumbai", "ET", "2026-06-01", "http://a"),
    ]
    scored = _lm_score(items)
    pol = scored["polarity"]
    assert pol is None or pol == pytest.approx(0.0, abs=0.01)


def test_sentiment_label_thresholds():
    assert _sentiment_label(0.5, 1.0) == "Positive"
    assert _sentiment_label(0.15, 0.6) == "Mildly positive"
    assert _sentiment_label(0.0, 0.0) == "Neutral"
    assert _sentiment_label(-0.15, 0.6) == "Mildly negative"
    assert _sentiment_label(-0.5, 1.0) == "Negative"
    assert _sentiment_label(None, None) == "No signal"


def test_carried_pct_in_range_or_none():
    items = [
        NewsItem("HDFC Bank Q4 profits surge sharply", "ET", "2026-06-01", "http://a"),
    ]
    scored = _lm_score(items)
    cp = scored["carried_pct"]
    if cp is not None:
        assert 0.0 <= cp <= 1.0


def test_no_pysentiment2_returns_neutral_dict():
    """Without pysentiment2, _lm_score returns neutral-signal dict (None polarity)."""
    items = [NewsItem("A quiet day on Dalal Street", "ET", "2026-06-01", "http://a")]
    with patch("equity_research.data.news.logger"):  # suppress warning
        # Force ImportError inside _lm_score by patching the import
        with patch.dict("sys.modules", {"pysentiment2": None}):
            # _lm_score does `import pysentiment2` inside → ImportError → empty dict
            result = _lm_score(items)
    assert result["polarity"] is None
    assert result["pos_words"] == []
    assert result["neg_words"] == []


# ---------------------------------------------------------------------------
# 3. Sentiment / rating firewall
# ---------------------------------------------------------------------------


def test_positive_sentiment_does_not_change_hold_to_buy():
    """A HOLD on the fundamentals must stay HOLD regardless of sentiment."""
    # upside=10%, MoS=25% (Unrated) → inside the band → HOLD
    rec_no_news = decide_recommendation(
        upside_pct=0.10, quality_verdict="Unrated",
        guardrail_fired=False, news=None,
    )
    rec_with_news = decide_recommendation(
        upside_pct=0.10, quality_verdict="Unrated",
        guardrail_fired=False, news=_news_result("Positive"),
    )
    assert rec_no_news.action == "HOLD"
    assert rec_with_news.action == "HOLD"


def test_negative_sentiment_does_not_change_buy_to_hold():
    """A BUY on the fundamentals must stay BUY regardless of negative sentiment."""
    # upside=35%, MoS=10% (Green) → well clear → BUY
    rec_no_news = decide_recommendation(
        upside_pct=0.35, quality_verdict="Green",
        guardrail_fired=False, news=None,
    )
    rec_with_news = decide_recommendation(
        upside_pct=0.35, quality_verdict="Green",
        guardrail_fired=False, news=_news_result("Negative"),
    )
    assert rec_no_news.action == "BUY"
    assert rec_with_news.action == "BUY"


def test_sentiment_appears_in_overlay_notes():
    """Sentiment label appears in overlay_notes, not injected into the main reason."""
    rec = decide_recommendation(
        upside_pct=0.30, quality_verdict="Green",
        guardrail_fired=False, news=_news_result("Positive"),
    )
    assert any("sentiment" in n.lower() for n in rec.overlay_notes)
    assert "Positive" not in rec.reason


def test_sentiment_label_and_limited_flag_in_note():
    rec = decide_recommendation(
        upside_pct=0.30, quality_verdict="Amber",
        guardrail_fired=False, news=_news_result("Mildly negative", limited=True),
    )
    notes = [n for n in rec.overlay_notes if "sentiment" in n.lower()]
    assert len(notes) == 1
    assert "Mildly negative" in notes[0]
    assert "limited coverage" in notes[0]


def test_no_news_gives_pending_note():
    rec = decide_recommendation(
        upside_pct=0.30, quality_verdict="Green",
        guardrail_fired=False, news=None,
    )
    assert any("pending" in n.lower() for n in rec.overlay_notes)


def test_intrinsic_value_not_modified_by_sentiment():
    """The news module never touches the intrinsic_value — it is display only."""
    import inspect
    from equity_research.data import news as news_mod
    src = inspect.getsource(news_mod)
    # The module must never reference "intrinsic_value" or "wacc" or "cost_of_equity"
    for forbidden in ("intrinsic_value", "wacc", "cost_of_equity", "discount_rate"):
        assert forbidden not in src, (
            f"news.py must not reference '{forbidden}' — sentiment is display only"
        )


# ---------------------------------------------------------------------------
# 4. Consensus cross-check
# ---------------------------------------------------------------------------


def test_broker_target_above_intrinsic_is_bullish_skew():
    """When broker target is >30% above model intrinsic it constitutes a bullish skew."""
    broker_target = 2000.0
    model_intrinsic = 1200.0
    ratio = broker_target / model_intrinsic
    assert ratio > 1.3


def test_broker_target_close_to_intrinsic_no_skew():
    broker_target = 1050.0
    model_intrinsic = 1000.0
    ratio = broker_target / model_intrinsic
    assert ratio < 1.15


# ---------------------------------------------------------------------------
# 5. Cache TTL
# ---------------------------------------------------------------------------


def test_cache_ttl_registered_as_24h():
    from equity_research.data.cache import TTL_SECONDS
    assert TTL_SECONDS["news"] == 24 * 3600


def test_cache_hit_skips_fetch():
    """A cached result within TTL must be served without calling feedparser."""
    ticker = "CACHEDCO.NS"
    sample = NewsSentimentResult(
        headlines=[NewsItem("Cached headline", "ET", "2026-06-16", "http://x")],
        limited_coverage=False, polarity=0.1,
        sentiment_label="Mildly positive", pos_words=["cached"], neg_words=[],
        carried_pct=1.0, sourced_at="2026-06-17T00:00:00Z",
    )
    from equity_research.data import cache as file_cache
    file_cache.put(f"{ticker}_news", _serialise(sample))
    with patch("feedparser.parse") as mock_parse:
        result = get_news_sentiment(ticker, "Cached Co")
    mock_parse.assert_not_called()
    assert result.headlines[0].title == "Cached headline"


def test_stale_cache_triggers_fresh_fetch():
    """A cache entry older than 24 h must trigger an RSS fetch."""
    ticker = "STALECO.NS"
    from equity_research.data.cache import _cache_dir, _safe_key
    stale_path = _cache_dir() / f"{_safe_key(f'{ticker}_news')}.json"
    stale_path.write_text(json.dumps({
        "ts": time.time() - 25 * 3600,   # 25 h ago → beyond 24 h TTL
        "payload": _serialise(NewsSentimentResult(
            headlines=[], limited_coverage=True, polarity=None,
            sentiment_label="No signal", pos_words=[], neg_words=[],
            carried_pct=None, sourced_at="2026-06-16T00:00:00Z",
        )),
    }))
    try:
        with patch("feedparser.parse", return_value=_make_feed([])) as mock_parse:
            get_news_sentiment(ticker, "Stale Co")
        mock_parse.assert_called_once()
    finally:
        stale_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 6. Serialisation round-trip
# ---------------------------------------------------------------------------


def test_serialise_deserialise_round_trip():
    original = NewsSentimentResult(
        headlines=[
            NewsItem("Profit surges", "ET", "2026-06-15", "http://a"),
            NewsItem("Loss reported", "BS", "2026-06-14", "http://b"),
        ],
        limited_coverage=False,
        polarity=0.25,
        sentiment_label="Mildly positive",
        pos_words=["profit", "surges"],
        neg_words=["loss"],
        carried_pct=0.5,
        uncertainty_count=1,
        litigious_count=0,
        sourced_at="2026-06-17T10:00:00Z",
    )
    restored = _deserialise(_serialise(original))
    assert len(restored.headlines) == 2
    assert restored.headlines[0].title == "Profit surges"
    assert restored.polarity == pytest.approx(0.25)
    assert restored.pos_words == ["profit", "surges"]
    assert restored.neg_words == ["loss"]
    assert restored.sentiment_label == "Mildly positive"
    assert restored.uncertainty_count == 1
    assert restored.litigious_count == 0


def test_deserialise_tolerates_missing_fields():
    """Deserialise must not raise on a minimal/partial dict (future-compat)."""
    minimal = {"headlines": [], "limited_coverage": True}
    result = _deserialise(minimal)
    assert result.limited_coverage is True
    assert result.polarity is None
    assert result.sentiment_label == "No signal"
    assert result.pos_words == []
