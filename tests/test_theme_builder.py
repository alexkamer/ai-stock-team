"""Tests for the pure-Python parts of agents/theme_builder.py: candidate
selection/backfill, weight normalization, momentum/size scoring, and
formula-mode's error tolerance. build_ai_allocation itself (LLM + network)
is exercised at the integration level, not here.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.theme_builder import (
    _MIN_PICKS,
    _min_max_normalize,
    _normalize_weights,
    _select_candidates,
    build_formula_allocation,
)
from core.db import Base
from core.models_db import User


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="a@example.com", password_hash="x")
    session.add(user)
    session.commit()
    yield session
    session.close()


def _result(ticker, verdict, predicted_price=None, error=None):
    r = {"ticker": ticker, "verdict": verdict}
    if predicted_price is not None:
        r["predicted_price"] = predicted_price
    if error is not None:
        r["error"] = error
    return r


def test_select_candidates_returns_buys_when_enough():
    results = [_result("A", "buy"), _result("B", "buy"), _result("C", "buy"), _result("D", "hold")]
    prices = {"A": 100, "B": 100, "C": 100, "D": 100}

    picks = _select_candidates(results, prices)

    assert [p["ticker"] for p in picks] == ["A", "B", "C"]


def test_select_candidates_backfills_holds_by_upside_when_too_few_buys():
    results = [
        _result("A", "buy"),
        _result("B", "hold", predicted_price=90),  # -10% upside
        _result("C", "hold", predicted_price=120),  # +20% upside
        _result("D", "hold", predicted_price=105),  # +5% upside
    ]
    prices = {"A": 100, "B": 100, "C": 100, "D": 100}

    picks = _select_candidates(results, prices)

    assert len(picks) == _MIN_PICKS
    assert [p["ticker"] for p in picks] == ["A", "C", "D"]


def test_select_candidates_skips_errored_results():
    results = [_result("A", "buy"), _result("B", "buy"), {"ticker": "C", "error": "boom"}]
    prices = {"A": 100, "B": 100}

    picks = _select_candidates(results, prices)

    assert [p["ticker"] for p in picks] == ["A", "B"]


def _pick(ticker, weight, rationale="because"):
    return (ticker, weight, rationale)


def test_normalize_weights_sums_to_100():
    picks = [_pick("A", 50), _pick("B", 30), _pick("C", 40)]

    normalized = _normalize_weights(picks)

    assert sum(weight for _, weight, _ in normalized) == pytest.approx(100.0)


def test_normalize_weights_clamps_dominant_pick():
    picks = [_pick("A", 90), _pick("B", 5), _pick("C", 5)]

    normalized = _normalize_weights(picks)
    by_ticker = {ticker: weight for ticker, weight, _ in normalized}

    assert by_ticker["A"] < 90
    assert sum(by_ticker.values()) == pytest.approx(100.0)


def test_normalize_weights_falls_back_to_equal_when_all_zero():
    picks = [_pick("A", 0), _pick("B", 0)]

    normalized = _normalize_weights(picks)

    assert [weight for _, weight, _ in normalized] == [50.0, 50.0]


def test_min_max_normalize_scales_to_unit_range():
    assert _min_max_normalize([10.0, 20.0, 30.0]) == [0.0, 0.5, 1.0]


def test_min_max_normalize_returns_midpoint_when_uniform():
    assert _min_max_normalize([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]


def test_build_formula_allocation_returns_empty_result_for_no_tickers(db):
    result = build_formula_allocation("some-theme", 1000.0, [], db=db, user_id=1)

    assert result["picks"] == []


def test_build_formula_allocation_skips_tickers_with_missing_data(db):
    def fake_price_performance(ticker):
        if ticker == "BAD":
            raise ValueError("no data")
        return {"3_month": 10.0}

    def fake_market_cap(ticker):
        return 5e10

    def fake_price(ticker):
        if ticker == "BAD":
            raise ValueError("no price")
        return 100.0

    with (
        patch("agents.theme_builder.get_price_performance", side_effect=fake_price_performance),
        patch("agents.theme_builder.get_market_cap", side_effect=fake_market_cap),
        patch("agents.theme_builder.get_stock_price", side_effect=fake_price),
    ):
        result = build_formula_allocation("some-theme", 1000.0, ["GOOD", "BAD"], db=db, user_id=1)

    assert [p["ticker"] for p in result["picks"]] == ["GOOD"]
    assert result["picks"][0]["verdict"] is None
