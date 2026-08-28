"""Logs Stock Team verdicts (at most one per ticker per calendar day) and
lazily scores them against a benchmark at fixed horizons.

No background job is needed to "check in" at the 1-week/1-month mark:
historical price data is queryable for any past date regardless of when you
ask, so a verdict logged 47 days ago can have its exact 7-day/30-day return
computed right now, correctly, from the real historical close on that exact
calendar date.
"""

import bisect
import json
from datetime import date, datetime, timedelta, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from core.models import TeamVerdict
from core.models_db import SpecialistCallRecord, TeamVerdictRecord

BENCHMARK = "SPY"
HORIZONS_DAYS = {"1w": 7, "1mo": 30, "3mo": 90}
HOLD_BAND_PERCENT = 3.0

# SpecialistFinding.signal ("positive"/"neutral"/"negative", core/models.py)
# maps onto the same buy/hold/sell hit logic _is_hit() already judges the
# aggregate verdict with - a specialist's positive lean is a "buy" call in
# the same sense that this ticker should have outperformed the benchmark.
_SIGNAL_TO_VERDICT = {"positive": "buy", "neutral": "hold", "negative": "sell"}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def log_verdict(
    db: DbSession,
    user_id: int,
    ticker: str,
    price_at_call: float,
    verdict: TeamVerdict,
    specialist_calls: list[dict] | None = None,
) -> None:
    """No-op if this ticker already has a logged verdict for today -
    regenerating later the same day just refreshes the on-screen view, it
    doesn't create a second row (and the freshly-run specialists' signals
    aren't persisted either, for the same reason)."""
    today = _today()
    already_logged = db.execute(
        select(TeamVerdictRecord.id).where(
            TeamVerdictRecord.user_id == user_id,
            TeamVerdictRecord.ticker == ticker,
            TeamVerdictRecord.call_date == today,
        )
    ).first()
    if already_logged:
        return

    record = TeamVerdictRecord(
        user_id=user_id,
        ticker=ticker,
        verdict=verdict.verdict,
        key_factors=json.dumps(verdict.key_factors),
        reasoning=verdict.reasoning,
        price_at_call=price_at_call,
        predicted_price=verdict.predicted_price,
        predicted_horizon=verdict.predicted_horizon,
        call_date=today,
    )
    db.add(record)
    db.flush()  # assigns record.id, needed by the FK below

    for call in specialist_calls or []:
        db.add(
            SpecialistCallRecord(
                team_verdict_id=record.id,
                specialist_key=call["specialist_key"],
                signal=call["signal"],
            )
        )
    db.commit()


def _closes_since(ticker: str, start_date: date):
    history = yf.Ticker(ticker).history(start=start_date)
    return None if history.empty else history["Close"]


def _price_on_or_after(closes, target_date: date) -> float | None:
    """First trading-day close on/after target_date, or None if that date
    hasn't happened yet or is past the end of available history."""
    if closes is None:
        return None
    dates = [ts.date() for ts in closes.index]
    pos = bisect.bisect_left(dates, target_date)
    return None if pos >= len(dates) else float(closes.iloc[pos])


def _is_hit(verdict: str, alpha_percent: float) -> bool:
    if verdict == "buy":
        return alpha_percent > 0
    if verdict == "sell":
        return alpha_percent < 0
    return abs(alpha_percent) <= HOLD_BAND_PERCENT


def _price_target_score(record: TeamVerdictRecord, ticker_closes) -> dict | None:
    """None if this record predates the predicted-price feature (nullable
    columns on older rows)."""
    if record.predicted_price is None or record.predicted_horizon is None:
        return None

    horizon_days = HORIZONS_DAYS[record.predicted_horizon]
    elapsed_days = (_today() - record.call_date).days
    base = {"predicted_price": record.predicted_price, "horizon": record.predicted_horizon}

    if elapsed_days < horizon_days:
        return {"status": "pending", **base}

    actual_price = _price_on_or_after(ticker_closes, record.call_date + timedelta(days=horizon_days))
    if actual_price is None:
        return {"status": "unavailable", **base}

    return {
        "status": "scored",
        **base,
        "actual_price": actual_price,
        "percent_diff": (actual_price - record.predicted_price) / record.predicted_price * 100,
    }


def score_record(record: TeamVerdictRecord) -> dict:
    ticker_closes = _closes_since(record.ticker, record.call_date)
    benchmark_closes = _closes_since(BENCHMARK, record.call_date)
    benchmark_at_call = _price_on_or_after(benchmark_closes, record.call_date)

    def _score_as_of(target_date: date) -> dict | None:
        ticker_price = _price_on_or_after(ticker_closes, target_date)
        benchmark_price = _price_on_or_after(benchmark_closes, target_date)
        if ticker_price is None or benchmark_price is None or benchmark_at_call is None:
            return None
        ticker_return = (ticker_price - record.price_at_call) / record.price_at_call * 100
        benchmark_return = (benchmark_price - benchmark_at_call) / benchmark_at_call * 100
        alpha = ticker_return - benchmark_return
        return {
            "ticker_return_percent": ticker_return,
            "benchmark_return_percent": benchmark_return,
            "alpha_percent": alpha,
            "hit": _is_hit(record.verdict, alpha),
        }

    today = _today()
    elapsed_days = (today - record.call_date).days

    horizons = {}
    for label, horizon_days in HORIZONS_DAYS.items():
        if elapsed_days < horizon_days:
            horizons[label] = {"status": "pending"}
            continue
        scored = _score_as_of(record.call_date + timedelta(days=horizon_days))
        horizons[label] = {"status": "scored", **scored} if scored else {"status": "unavailable"}

    current = _score_as_of(today)

    specialist_calls = [
        {
            "specialist_key": call.specialist_key,
            "signal": call.signal,
            "alpha_percent": current["alpha_percent"] if current else None,
            "hit": _is_hit(_SIGNAL_TO_VERDICT[call.signal], current["alpha_percent"]) if current else None,
        }
        for call in record.specialist_calls
    ]

    return {
        "id": record.id,
        "ticker": record.ticker,
        "verdict": record.verdict,
        "key_factors": json.loads(record.key_factors),
        "reasoning": record.reasoning,
        "price_at_call": record.price_at_call,
        "call_date": record.call_date.isoformat(),
        "current": current,
        "horizons": horizons,
        "price_target": _price_target_score(record, ticker_closes),
        "specialist_calls": specialist_calls,
    }


def aggregate_stats(scored_records: list[dict]) -> dict:
    with_current = [r for r in scored_records if r["current"] is not None]
    hits = sum(1 for r in with_current if r["current"]["hit"])

    avg_alpha_by_verdict = {}
    for verdict in ("buy", "hold", "sell"):
        alphas = [r["current"]["alpha_percent"] for r in with_current if r["verdict"] == verdict]
        avg_alpha_by_verdict[verdict] = sum(alphas) / len(alphas) if alphas else None

    return {
        "total_calls": len(scored_records),
        "scored_calls": len(with_current),
        "hit_rate_percent": (hits / len(with_current) * 100) if with_current else None,
        "avg_alpha_by_verdict": avg_alpha_by_verdict,
    }


def specialist_stats(scored_records: list[dict]) -> dict:
    """Per-specialist accuracy, flattened across every scored record
    regardless of ticker - a specialist's calibration is a property of the
    agent, not of any one ticker, so this deliberately isn't ticker-scoped
    the way `scored_records` passed to `aggregate_stats` may be."""
    calls_by_specialist: dict[str, list[dict]] = {}
    for record in scored_records:
        for call in record["specialist_calls"]:
            calls_by_specialist.setdefault(call["specialist_key"], []).append(call)

    stats = {}
    for specialist_key, calls in calls_by_specialist.items():
        scored = [c for c in calls if c["hit"] is not None]
        hits = sum(1 for c in scored if c["hit"])
        stats[specialist_key] = {
            "total_calls": len(calls),
            "scored_calls": len(scored),
            "hit_rate_percent": (hits / len(scored) * 100) if scored else None,
        }
    return stats
