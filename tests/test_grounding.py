"""Tests for core/grounding.py's numeric-citation check on specialist findings."""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from core.grounding import check_findings_are_grounded
from core.models import SpecialistFinding


def _ctx(tool_results: dict):
    """Fake RunContext exposing just the .messages attribute the validator
    reads - one ModelRequest per tool result, mirroring what pydantic-ai's
    real message history looks like after a tool call.
    """
    messages = [
        ModelRequest(parts=[ToolReturnPart(tool_name=name, content=content, tool_call_id="x")])
        for name, content in tool_results.items()
    ]
    return SimpleNamespace(messages=messages)


def _finding(headline: str, key_points: list[str]) -> SpecialistFinding:
    return SpecialistFinding(signal="neutral", headline=headline, key_points=key_points)


def test_passes_when_no_tool_results_to_check_against():
    finding = _finding("Anything goes.", ["No tools ran, e.g. portfolio_fit or sentiment."])
    assert check_findings_are_grounded(_ctx({}), finding) is finding


def test_passes_when_cited_number_matches_tool_result_exactly():
    ctx = _ctx({"get_technical_indicators": {"rsi_14": 45.4956}})
    finding = _finding("RSI is neutral.", ["RSI-14 sits at 45.4956, in neutral territory."])
    assert check_findings_are_grounded(ctx, finding) is finding


def test_passes_within_rounding_tolerance():
    ctx = _ctx({"get_price_performance": {"1_year": 177.93035862679588}})
    finding = _finding("Strong 1-year gain.", ["Up 177.9% over the past year."])
    assert check_findings_are_grounded(ctx, finding) is finding


def test_passes_on_percent_vs_fraction_scale_mismatch():
    # yfinance returns margins as a fraction (0.65); a specialist reporting
    # "65%" is citing the same figure, not hallucinating a new one.
    ctx = _ctx({"get_ticker_overview": {"gross_margins": 0.65}})
    finding = _finding("Healthy margins.", ["Gross margins of 65% are well above peers."])
    assert check_findings_are_grounded(ctx, finding) is finding


def test_passes_on_market_cap_abbreviated_to_trillions():
    ctx = _ctx({"get_market_cap": 2_800_000_000_000.0})
    finding = _finding("Mega-cap.", ["Market cap of $2.8T dwarfs smaller peers."])
    assert check_findings_are_grounded(ctx, finding) is finding


def test_raises_model_retry_on_unmatched_figure():
    ctx = _ctx({"get_pe_ratio": 28.4})
    finding = _finding("Cheap on earnings.", ["Trading at a P/E of 12.1, a steep discount."])
    with pytest.raises(ModelRetry):
        check_findings_are_grounded(ctx, finding)


def test_passes_on_percent_below_high_derived_from_two_pool_numbers():
    # "19.5% below its 52-week high" is arithmetically correct (computed
    # from two real tool numbers) but isn't itself a number either tool
    # call returned - the false positive this test guards against caused a
    # real production failure (a legitimate finding got ModelRetry'd twice
    # and the whole run crashed with UnexpectedModelBehavior).
    ctx = _ctx({"get_ticker_stats": {"fifty_two_week_high": 584.73}, "get_stock_price": 471.6})
    percent_below_high = (584.73 - 471.6) / 584.73 * 100
    finding = _finding(
        "Well off its high.", [f"Trading {percent_below_high:.1f}% below its 52-week high of $584.73."]
    )
    assert check_findings_are_grounded(ctx, finding) is finding


def test_tolerates_a_minority_of_unmatched_figures():
    # Several correctly-cited numbers plus one truly-hallucinated one:
    # majority still matches, so this doesn't burn the agent's retry budget
    # on what's very likely a citation the checker just doesn't recognize.
    ctx = _ctx({"get_technical_indicators": {"rsi_14": 45.5, "macd": -7.61}})
    finding = _finding(
        "Mixed technicals.",
        ["RSI-14 at 45.5 is neutral.", "MACD of -7.61 is bearish.", "Stock is up 999.9% this quarter."],
    )
    assert check_findings_are_grounded(ctx, finding) is finding
