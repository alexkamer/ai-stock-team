"""Tests for models.py."""

import pytest
from pydantic import ValidationError

from core.models import CompanySnapshot


def make_snapshot_kwargs(**overrides):
    kwargs = {
        "ticker": "NVDA",
        "ticker_price": 193.25,
        "market_cap": 4.78e12,
        "pe_ratio": 29.6,
        "company_name": "NVIDIA Corporation",
        "sentiment": "bullish",
        "summary": "Doing fine.",
    }
    kwargs.update(overrides)
    return kwargs


def test_valid_snapshot_constructs():
    snapshot = CompanySnapshot(**make_snapshot_kwargs())

    assert snapshot.ticker == "NVDA"
    assert snapshot.ticker_price == 193.25


@pytest.mark.parametrize("field", ["ticker_price", "market_cap"])
def test_non_positive_values_are_rejected(field):
    with pytest.raises(ValidationError, match="must be positive"):
        CompanySnapshot(**make_snapshot_kwargs(**{field: -1.0}))


@pytest.mark.parametrize("field", ["ticker_price", "market_cap"])
def test_zero_is_rejected(field):
    with pytest.raises(ValidationError, match="must be positive"):
        CompanySnapshot(**make_snapshot_kwargs(**{field: 0.0}))


def test_negative_pe_ratio_is_allowed():
    # Unlike price/market cap, a negative P/E is a real, legitimate value
    # for a company with negative trailing earnings - it should NOT be
    # rejected by the same positivity check.
    snapshot = CompanySnapshot(**make_snapshot_kwargs(pe_ratio=-12.5))

    assert snapshot.pe_ratio == -12.5


def test_invalid_sentiment_is_rejected():
    with pytest.raises(ValidationError):
        CompanySnapshot(**make_snapshot_kwargs(sentiment="ecstatic"))
