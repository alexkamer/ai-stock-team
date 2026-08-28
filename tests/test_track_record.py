"""Tests for core/track_record.py: verdict logging (dedupe per ticker per
day) and lazy scoring against a benchmark. Mocks yf.Ticker so scoring
doesn't hit the network - same approach as test_tools.py.
"""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.models import TeamVerdict
from core.models_db import SpecialistCallRecord, TeamVerdictRecord, User
from core.track_record import aggregate_stats, get_todays_verdict, log_verdict, score_record, specialist_stats


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="a@example.com", password_hash="x")
    session.add(user)
    session.commit()
    yield session, user.id
    session.close()


def _verdict(**overrides):
    args = {
        "ticker": "NVDA",
        "verdict": "buy",
        "key_factors": ["Fundamentals: strong."],
        "reasoning": "Strong across the board.",
        "predicted_price": 220.0,
        "predicted_horizon": "1mo",
    }
    args.update(overrides)
    return TeamVerdict(**args)


def test_log_verdict_inserts_a_row(db):
    session, user_id = db
    log_verdict(session, user_id, "NVDA", 200.0, _verdict())

    rows = session.execute(select(TeamVerdictRecord)).scalars().all()
    assert len(rows) == 1
    assert rows[0].ticker == "NVDA"
    assert rows[0].price_at_call == 200.0
    assert rows[0].predicted_price == 220.0
    assert rows[0].predicted_horizon == "1mo"
    assert json.loads(rows[0].key_factors) == ["Fundamentals: strong."]


def test_log_verdict_is_a_noop_for_a_second_call_same_day(db):
    session, user_id = db
    log_verdict(session, user_id, "NVDA", 200.0, _verdict())
    log_verdict(session, user_id, "NVDA", 205.0, _verdict(verdict="sell"))

    rows = session.execute(select(TeamVerdictRecord)).scalars().all()
    assert len(rows) == 1
    assert rows[0].price_at_call == 200.0
    assert rows[0].verdict == "buy"


def test_log_verdict_allows_different_tickers_same_day(db):
    session, user_id = db
    log_verdict(session, user_id, "NVDA", 200.0, _verdict())
    log_verdict(session, user_id, "AAPL", 250.0, _verdict(ticker="AAPL"))

    rows = session.execute(select(TeamVerdictRecord)).scalars().all()
    assert {r.ticker for r in rows} == {"NVDA", "AAPL"}


def test_log_verdict_persists_specialist_calls(db):
    session, user_id = db
    log_verdict(
        session,
        user_id,
        "NVDA",
        200.0,
        _verdict(),
        specialist_calls=[
            {"specialist_key": "get_fundamentals", "signal": "positive"},
            {"specialist_key": "get_risk", "signal": "neutral"},
        ],
    )

    rows = session.execute(select(SpecialistCallRecord)).scalars().all()
    assert {(r.specialist_key, r.signal) for r in rows} == {
        ("get_fundamentals", "positive"),
        ("get_risk", "neutral"),
    }
    verdict_id = session.execute(select(TeamVerdictRecord.id)).scalar_one()
    assert all(r.team_verdict_id == verdict_id for r in rows)


def test_log_verdict_skips_specialist_calls_on_same_day_noop(db):
    session, user_id = db
    log_verdict(
        session, user_id, "NVDA", 200.0, _verdict(), specialist_calls=[{"specialist_key": "get_risk", "signal": "positive"}]
    )
    log_verdict(
        session, user_id, "NVDA", 205.0, _verdict(), specialist_calls=[{"specialist_key": "get_risk", "signal": "negative"}]
    )

    rows = session.execute(select(SpecialistCallRecord)).scalars().all()
    assert len(rows) == 1
    assert rows[0].signal == "positive"


def test_get_todays_verdict_returns_none_when_not_logged(db):
    session, user_id = db
    assert get_todays_verdict(session, user_id, "NVDA") is None


def test_get_todays_verdict_returns_the_logged_row(db):
    session, user_id = db
    log_verdict(session, user_id, "NVDA", 200.0, _verdict(verdict="sell"))

    found = get_todays_verdict(session, user_id, "NVDA")
    assert found is not None
    assert found.verdict == "sell"


def _record(call_date, price_at_call=200.0, verdict="buy", predicted_price=None, predicted_horizon=None):
    return TeamVerdictRecord(
        id=1,
        user_id=1,
        ticker="NVDA",
        verdict=verdict,
        key_factors=json.dumps(["x"]),
        reasoning="y",
        price_at_call=price_at_call,
        predicted_price=predicted_price,
        predicted_horizon=predicted_horizon,
        call_date=call_date,
    )


def _mock_ticker_history(nvda_daily_return: float, spy_daily_return: float, days: int, start: date):
    dates = pd.bdate_range(start, periods=days)

    def side_effect(symbol):
        rate = spy_daily_return if symbol == "SPY" else nvda_daily_return
        base = 100.0 if symbol == "SPY" else 200.0
        closes = [base * (1 + rate) ** i for i in range(days)]
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame({"Close": closes}, index=dates)
        return mock_ticker

    return side_effect


@patch("core.track_record.yf.Ticker")
def test_score_record_scores_elapsed_horizons_and_flags_pending(mock_ticker_cls):
    call_date = date.today() - timedelta(days=40)
    # NVDA well outpacing SPY every day since the call.
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.005, spy_daily_return=0.0005, days=60, start=call_date
    )

    scored = score_record(_record(call_date, verdict="buy"))

    assert scored["horizons"]["1w"]["status"] == "scored"
    assert scored["horizons"]["1mo"]["status"] == "scored"
    assert scored["horizons"]["3mo"]["status"] == "pending"
    assert scored["horizons"]["1w"]["alpha_percent"] > 0
    assert scored["horizons"]["1w"]["hit"] is True
    assert scored["current"]["alpha_percent"] > 0
    assert scored["current"]["hit"] is True


@patch("core.track_record.yf.Ticker")
def test_score_record_sell_verdict_hits_on_negative_alpha(mock_ticker_cls):
    call_date = date.today() - timedelta(days=10)
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.005, spy_daily_return=0.0005, days=20, start=call_date
    )

    scored = score_record(_record(call_date, verdict="sell"))

    # Positive alpha - bad news for a "sell" call.
    assert scored["current"]["alpha_percent"] > 0
    assert scored["current"]["hit"] is False


@patch("core.track_record.yf.Ticker")
def test_score_record_hold_verdict_hits_within_band(mock_ticker_cls):
    call_date = date.today() - timedelta(days=10)
    # NVDA and SPY move almost identically - alpha near zero.
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.0005, spy_daily_return=0.0005, days=20, start=call_date
    )

    scored = score_record(_record(call_date, verdict="hold"))

    assert abs(scored["current"]["alpha_percent"]) < 1.0
    assert scored["current"]["hit"] is True


@patch("core.track_record.yf.Ticker")
def test_score_record_unavailable_when_no_history(mock_ticker_cls):
    call_date = date.today() - timedelta(days=10)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_ticker

    scored = score_record(_record(call_date))

    assert scored["current"] is None
    assert scored["price_target"] is None


@patch("core.track_record.yf.Ticker")
def test_score_record_price_target_is_none_for_pre_feature_rows(mock_ticker_cls):
    call_date = date.today() - timedelta(days=40)
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.005, spy_daily_return=0.0005, days=60, start=call_date
    )

    scored = score_record(_record(call_date, predicted_price=None, predicted_horizon=None))

    assert scored["price_target"] is None


@patch("core.track_record.yf.Ticker")
def test_score_record_price_target_pending_before_horizon_elapses(mock_ticker_cls):
    call_date = date.today() - timedelta(days=10)
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.005, spy_daily_return=0.0005, days=20, start=call_date
    )

    scored = score_record(_record(call_date, predicted_price=220.0, predicted_horizon="1mo"))

    assert scored["price_target"] == {"status": "pending", "predicted_price": 220.0, "horizon": "1mo"}


@patch("core.track_record.yf.Ticker")
def test_score_record_price_target_scored_after_horizon_elapses(mock_ticker_cls):
    call_date = date.today() - timedelta(days=10)
    # NVDA starts at 200 and grows ~0.5%/day - after 7 days (the 1w horizon),
    # it should be noticeably above the 205.0 target.
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.005, spy_daily_return=0.0005, days=20, start=call_date
    )

    scored = score_record(_record(call_date, predicted_price=205.0, predicted_horizon="1w"))

    assert scored["price_target"]["status"] == "scored"
    assert scored["price_target"]["predicted_price"] == 205.0
    assert scored["price_target"]["horizon"] == "1w"
    assert scored["price_target"]["actual_price"] > 205.0
    assert scored["price_target"]["percent_diff"] > 0


@patch("core.track_record.yf.Ticker")
def test_score_record_scores_specialist_calls_against_the_same_alpha(mock_ticker_cls):
    call_date = date.today() - timedelta(days=10)
    # NVDA well outpacing SPY - positive alpha.
    mock_ticker_cls.side_effect = _mock_ticker_history(
        nvda_daily_return=0.005, spy_daily_return=0.0005, days=20, start=call_date
    )
    record = _record(call_date, verdict="buy")
    record.specialist_calls = [
        SpecialistCallRecord(specialist_key="get_fundamentals", signal="positive"),
        SpecialistCallRecord(specialist_key="get_risk", signal="negative"),
        SpecialistCallRecord(specialist_key="get_valuation", signal="neutral"),
    ]

    scored = score_record(record)
    by_key = {c["specialist_key"]: c for c in scored["specialist_calls"]}

    assert by_key["get_fundamentals"]["hit"] is True  # positive signal, positive alpha
    assert by_key["get_risk"]["hit"] is False  # negative signal, positive alpha
    assert by_key["get_valuation"]["hit"] is False  # neutral signal, alpha outside hold band


def test_specialist_stats_groups_hit_rate_by_specialist():
    scored_records = [
        {
            "specialist_calls": [
                {"specialist_key": "get_fundamentals", "signal": "positive", "alpha_percent": 5.0, "hit": True},
                {"specialist_key": "get_risk", "signal": "negative", "alpha_percent": 5.0, "hit": False},
            ]
        },
        {
            "specialist_calls": [
                {"specialist_key": "get_fundamentals", "signal": "positive", "alpha_percent": -1.0, "hit": False},
                {"specialist_key": "get_risk", "signal": None, "alpha_percent": None, "hit": None},
            ]
        },
    ]

    stats = specialist_stats(scored_records)

    assert stats["get_fundamentals"] == {"total_calls": 2, "scored_calls": 2, "hit_rate_percent": pytest.approx(50.0)}
    assert stats["get_risk"] == {"total_calls": 2, "scored_calls": 1, "hit_rate_percent": 0.0}


def test_aggregate_stats_computes_hit_rate_and_avg_alpha():
    scored_records = [
        {"verdict": "buy", "current": {"alpha_percent": 5.0, "hit": True}},
        {"verdict": "buy", "current": {"alpha_percent": -2.0, "hit": False}},
        {"verdict": "sell", "current": {"alpha_percent": -3.0, "hit": True}},
        {"verdict": "hold", "current": None},
    ]

    stats = aggregate_stats(scored_records)

    assert stats["total_calls"] == 4
    assert stats["scored_calls"] == 3
    assert stats["hit_rate_percent"] == pytest.approx(2 / 3 * 100)
    assert stats["avg_alpha_by_verdict"]["buy"] == pytest.approx(1.5)
    assert stats["avg_alpha_by_verdict"]["sell"] == pytest.approx(-3.0)
    assert stats["avg_alpha_by_verdict"]["hold"] is None
