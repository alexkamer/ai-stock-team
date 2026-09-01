"""Themes tab - turns a theme's ticker universe into a dollar allocation,
two ways:

- build_formula_allocation: pure market data (3-month momentum + market
  cap), no LLM call at all - resolves in seconds, and doubles as a
  sanity check against the AI's picks.
- build_ai_allocation: reuses run_team_scan (stock_team.py) to vet every
  ticker first, then hands the buy/hold-rated survivors to an "allocator"
  agent that sizes each position by conviction.

Both share _normalize_weights (defensive clamp/renormalize) and compute
dollar amounts/share counts in Python, never trusted from the LLM.

A third thing lives here too: refresh_theme_suggestion/promote_theme_
suggestion/get_theme_suggestion, the shared "model portfolio" per theme
that replaced per-click building on the Themes tab - one ranked
allocation per theme_key that every user sees, refreshed on a schedule
(this file's CLI entry point) rather than per request. See
core/models_db.py's ThemeSuggestion docstring for the live/candidate
versioning.
"""

import argparse
import math
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session as DbSession

from core.config import load_agent
from core.models import ThemeAllocation
from core.models_db import ThemePortfolio, ThemePortfolioPick, ThemeSuggestion, ThemeSuggestionPick, ThemeSummary, _now
from core.themes import THEME_CATALOG, get_filings_relevance, get_theme, get_theme_universe
from core.tools import (
    get_annualized_volatility,
    get_day_change,
    get_eps,
    get_market_cap,
    get_price_performance,
    get_sector,
    get_stock_price,
    parallel_map,
    with_yf_retries,
)

_AGENT_RETRIES = 3
_MIN_PICKS = 3
_MAX_WEIGHT_PERCENT = 35.0
_BENCHMARK_TICKER = "SPY"
_FORMULA_MOMENTUM_WEIGHT = 0.6
_FORMULA_SIZE_WEIGHT = 0.4
_FORMULA_MIN_SCORE = 0.05  # floor so no pick gets ~0 weight just for being the smallest/slowest in the set

allocator_agent = load_agent(output_type=ThemeAllocation, retries=_AGENT_RETRIES)


def _upside(result: dict, prices: dict[str, float]) -> float:
    """Ranks hold-rated backfill candidates by predicted upside - falls
    back to 0 (no better/worse than flat) if a scan result is missing a
    prediction, e.g. it errored rather than producing a verdict."""
    predicted = result.get("predicted_price")
    price = prices.get(result["ticker"])
    if not predicted or not price:
        return 0.0
    return (predicted - price) / price


def _select_candidates(usable: list[dict], prices: dict[str, float]) -> list[dict]:
    """Buy-rated tickers first; if that's under _MIN_PICKS, backfill with
    the best hold-rated tickers by predicted upside so a thin-buy day still
    produces a diversified-enough basket instead of a 1-2 stock portfolio."""
    buys = [r for r in usable if r.get("verdict") == "buy"]
    if len(buys) >= _MIN_PICKS:
        return buys

    holds = sorted((r for r in usable if r.get("verdict") == "hold"), key=lambda r: _upside(r, prices), reverse=True)
    return buys + holds[: _MIN_PICKS - len(buys)]


def _normalize_weights(picks: list[tuple[str, float, str]]) -> list[tuple[str, float, str]]:
    """Clamps any single weight to _MAX_WEIGHT_PERCENT and renormalizes the
    whole set back to sum-to-100 - defensive, the same way get_team_analysis
    clamps a 'sell' verdict on a ticker the user doesn't hold, since neither
    an LLM's stated weights nor a formula's raw scores are arithmetic to
    trust outright without a final sanity pass."""
    clamped = [(ticker, min(weight, _MAX_WEIGHT_PERCENT), rationale) for ticker, weight, rationale in picks]
    total = sum(weight for _, weight, _ in clamped)
    if total <= 0:
        # All-zero/negative weights would otherwise divide-by-zero below -
        # falls back to equal weight rather than crashing the whole build.
        equal = 100.0 / len(clamped)
        return [(ticker, equal, rationale) for ticker, _, rationale in clamped]
    return [(ticker, weight / total * 100.0, rationale) for ticker, weight, rationale in clamped]


def _min_max_normalize(values: list[float]) -> list[float]:
    """Scales values to [0, 1] within this candidate set - the *relative*
    spread of momentum/size across today's specific theme universe is what
    should drive weight, not their absolute magnitude (a 5% 3mo gain means
    something different in a low-momentum theme than a high-momentum one).
    Returns 0.5 for every value if the set is uniform (min == max), rather
    than dividing by zero."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _empty_result(theme_key: str, amount: float, message: str) -> dict:
    return {
        "theme_key": theme_key,
        "amount": amount,
        "summary": message,
        "picks": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _persist(theme_key: str, amount: float, summary: str, picks: list[dict], method: str, db: DbSession, user_id: int) -> dict:
    record = ThemePortfolio(user_id=user_id, theme_key=theme_key, amount=amount, summary=summary, method=method)
    db.add(record)
    db.flush()
    for pick in picks:
        db.add(ThemePortfolioPick(theme_portfolio_id=record.id, **pick))
    db.commit()

    # current_price == price_at_buy right after a build - no extra fetch
    # needed, unlike get_theme_history which is enriching picks that were
    # bought at some point in the past.
    enriched_picks = [{**pick, "current_price": pick["price_at_buy"], "change_percent": 0.0} for pick in picks]

    return {
        "theme_key": theme_key,
        "amount": amount,
        "summary": summary,
        "picks": enriched_picks,
        "created_at": record.created_at.isoformat(),
    }


def _rank_tickers(tickers: list[str]) -> list[dict]:
    """The formula's core: 3-month momentum + market-cap composite score
    over live data, normalized to weight_percent - no LLM, no amount, no
    persistence, just tickers in and ranked {ticker, weight_percent,
    rationale, price} out. Shared by build_formula_allocation (a per-
    amount, per-user build) and refresh_theme_suggestion (the shared,
    amount-agnostic model portfolio) so the ranking logic has one home."""

    def _fetch(ticker: str) -> dict | None:
        try:
            momentum = get_price_performance(ticker).get("3_month")
            return {
                "ticker": ticker,
                "momentum": momentum if momentum is not None else 0.0,
                "market_cap": get_market_cap(ticker),
                "price": get_stock_price(ticker),
            }
        except ValueError:
            return None

    data = [d for d in parallel_map(_fetch, tickers) if d is not None]
    if not data:
        return []

    momentum_norm = _min_max_normalize([d["momentum"] for d in data])
    size_norm = _min_max_normalize([math.log10(d["market_cap"]) for d in data])
    raw_picks = [
        (
            d["ticker"],
            max(_FORMULA_MIN_SCORE, _FORMULA_MOMENTUM_WEIGHT * m + _FORMULA_SIZE_WEIGHT * s),
            f"3mo momentum {d['momentum']:+.1f}%, market cap ${d['market_cap'] / 1e9:.1f}B",
        )
        for d, m, s in zip(data, momentum_norm, size_norm)
    ]
    normalized = _normalize_weights(raw_picks)
    prices = {d["ticker"]: d["price"] for d in data}

    return [
        {"ticker": ticker, "weight_percent": round(weight_percent, 2), "rationale": rationale, "price": prices[ticker]}
        for ticker, weight_percent, rationale in normalized
    ]


def build_formula_allocation(theme_key: str, amount: float, tickers: list[str], db: DbSession, user_id: int) -> dict:
    """No LLM call anywhere in this function - weights come from a plain
    momentum + market-cap composite score over live data, so this resolves
    in the time it takes to fetch a handful of yfinance fields, not the
    minutes a full multi-agent scan takes (see build_ai_allocation)."""
    if not tickers:
        return _empty_result(theme_key, amount, "No tickers in this theme's universe today - try again another day.")

    ranked = _rank_tickers(tickers)
    if not ranked:
        return _empty_result(theme_key, amount, "Couldn't fetch live data for this theme's tickers - try again later.")

    picks = []
    for r in ranked:
        dollar_amount = amount * r["weight_percent"] / 100.0
        picks.append(
            {
                "ticker": r["ticker"],
                "verdict": None,
                "weight_percent": r["weight_percent"],
                "dollar_amount": round(dollar_amount, 2),
                "shares": round(dollar_amount / r["price"], 4),
                "rationale": r["rationale"],
                "price_at_buy": r["price"],
            }
        )

    summary = (
        f"Ranked by 3-month price momentum and market cap alone (no AI vetting) - "
        f"{len(picks)} of this theme's {len(tickers)} tickers had usable data."
    )
    return _persist(theme_key, amount, summary, picks, "formula", db, user_id)


async def build_ai_allocation(theme_key: str, amount: float, scan_results: list[dict], db: DbSession, user_id: int) -> dict:
    theme = get_theme(theme_key)
    usable = [r for r in scan_results if not r.get("error")]
    if not usable:
        return _empty_result(theme_key, amount, "No buy- or hold-rated picks came out of today's scan for this theme - try again another day.")

    def _safe_price(ticker: str) -> float | None:
        try:
            return get_stock_price(ticker)
        except Exception:
            return None

    tickers = [r["ticker"] for r in usable]
    prices = {t: p for t, p in zip(tickers, parallel_map(_safe_price, tickers)) if p is not None}

    # _select_candidates picks from `usable` by verdict alone, so a
    # buy-rated ticker whose price fetch just failed could still come back
    # - drop it here rather than at the f-string below, where it'd be a
    # KeyError instead of just one fewer candidate.
    candidates = [c for c in _select_candidates(usable, prices) if c["ticker"] in prices]
    if not candidates:
        return _empty_result(theme_key, amount, "No buy- or hold-rated picks came out of today's scan for this theme - try again another day.")

    candidate_lines = "\n".join(
        f"- {c['ticker']}: verdict={c['verdict']}, current price=${prices[c['ticker']]:.2f}, "
        f"predicted_price=${c.get('predicted_price')}, horizon={c.get('predicted_horizon')}"
        for c in candidates
    )
    result = await allocator_agent.run(
        f"Build a ${amount:,.2f} allocation across this theme's vetted stocks, weighting by conviction - "
        f"a stronger buy verdict and larger predicted upside should get more weight than a weaker buy or "
        f"a backfilled hold. No single pick should dominate; keep the basket diversified. Weights must sum "
        f"to 100.\n\nTheme: {theme['name']} - {theme['description']}\n\nCandidates:\n{candidate_lines}"
    )
    normalized = _normalize_weights([(p.ticker, p.weight_percent, p.rationale) for p in result.output.picks])

    picks = []
    for ticker, weight_percent, rationale in normalized:
        verdict = next(c["verdict"] for c in candidates if c["ticker"] == ticker)
        dollar_amount = amount * weight_percent / 100.0
        picks.append(
            {
                "ticker": ticker,
                "verdict": verdict,
                "weight_percent": round(weight_percent, 2),
                "dollar_amount": round(dollar_amount, 2),
                "shares": round(dollar_amount / prices[ticker], 4),
                "rationale": rationale,
                "price_at_buy": prices[ticker],
            }
        )

    return _persist(theme_key, amount, result.output.summary, picks, "ai_team", db, user_id)


def _fetch_current_prices(tickers: list[str]) -> dict[str, float | None]:
    """One live price fetch per distinct ticker, however many past
    portfolios/picks reference it - mirrors the dedup-by-symbol idea in
    track_record.score_records, just for a live quote instead of history."""
    if not tickers:
        return {}

    def _fetch(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, get_stock_price(ticker)
        except Exception:
            return ticker, None

    return dict(parallel_map(_fetch, tickers))


def _fetch_sectors(tickers: list[str]) -> dict[str, str]:
    """One sector lookup per distinct ticker, falling back to "Other" for
    a ticker yfinance has no sector for - the sector-grouped view on the
    Themes tab needs every pick bucketed somewhere, not a hole in the
    breakdown."""
    if not tickers:
        return {}

    def _fetch(ticker: str) -> tuple[str, str]:
        try:
            return ticker, get_sector(ticker)
        except Exception:
            return ticker, "Other"

    return dict(parallel_map(_fetch, tickers))


def get_theme_history(db: DbSession, user_id: int) -> list[dict]:
    portfolios = (
        db.query(ThemePortfolio)
        .filter(ThemePortfolio.user_id == user_id)
        .order_by(ThemePortfolio.created_at.desc())
        .all()
    )

    all_picks = [pick for p in portfolios for pick in p.picks]
    current_prices = _fetch_current_prices(sorted({pick.ticker for pick in all_picks if pick.price_at_buy}))

    def _serialize_pick(pick: ThemePortfolioPick) -> dict:
        current_price = current_prices.get(pick.ticker)
        change_percent = (
            round((current_price - pick.price_at_buy) / pick.price_at_buy * 100, 2)
            if current_price and pick.price_at_buy
            else None
        )
        return {
            "ticker": pick.ticker,
            "verdict": pick.verdict,
            "weight_percent": pick.weight_percent,
            "dollar_amount": pick.dollar_amount,
            "shares": pick.shares,
            "rationale": pick.rationale,
            "price_at_buy": pick.price_at_buy,
            "current_price": current_price,
            "change_percent": change_percent,
        }

    return [
        {
            "theme_key": p.theme_key,
            "amount": p.amount,
            "summary": p.summary,
            "method": p.method,
            "created_at": p.created_at.isoformat(),
            "picks": [_serialize_pick(pick) for pick in p.picks],
        }
        for p in portfolios
    ]


def _get_suggestion(db: DbSession, theme_key: str, status: str) -> ThemeSuggestion | None:
    return (
        db.query(ThemeSuggestion)
        .filter(ThemeSuggestion.theme_key == theme_key, ThemeSuggestion.status == status)
        .first()
    )


def refresh_theme_suggestion(theme_key: str, db: DbSession) -> dict:
    """Re-ranks a theme's universe and writes the result as a 'candidate'
    row (or, if the theme has no 'live' row yet, directly as 'live' - a
    first run has nothing to preserve). Meant to run on a schedule (see
    the CLI at the bottom of this file), not per user request - the
    Themes tab only ever reads whatever refresh_theme_suggestion last
    wrote, via get_theme_suggestion, and only promote_theme_suggestion
    ever turns a candidate into the live version users see."""
    tickers = get_theme_universe(theme_key)
    ranked = _rank_tickers(tickers)
    if not ranked:
        raise ValueError(f"Couldn't rank any tickers for theme {theme_key!r} - try again later")

    relevance = get_filings_relevance(theme_key)
    scores = [relevance[r["ticker"]]["relevance_score"] for r in ranked if r["ticker"] in relevance]
    quality_score = round(sum(scores) / len(scores), 3) if scores else None

    is_first_run = _get_suggestion(db, theme_key, "live") is None
    status = "live" if is_first_run else "candidate"
    summary = (
        f"Ranked by 3-month price momentum and market cap alone (no AI vetting) - "
        f"{len(ranked)} of this theme's {len(tickers)} tickers had usable data."
    )

    # ORM-level delete (not Query.delete()) so cascade="all, delete-orphan"
    # actually fires on the old row's picks - a bulk Query.delete() skips
    # the ORM entirely, orphaning the picks, and SQLite can then reuse the
    # deleted row's id for the new ThemeSuggestion below, silently
    # reattaching the orphaned picks to it (duplicate tickers, doubled
    # weight/dollar amounts).
    for old in db.query(ThemeSuggestion).filter(ThemeSuggestion.theme_key == theme_key, ThemeSuggestion.status == status):
        db.delete(old)
    db.flush()
    suggestion = ThemeSuggestion(
        theme_key=theme_key,
        status=status,
        summary=summary,
        quality_score=quality_score,
        promoted_at=_now() if is_first_run else None,
    )
    db.add(suggestion)
    db.flush()
    for r in ranked:
        db.add(
            ThemeSuggestionPick(
                theme_suggestion_id=suggestion.id,
                ticker=r["ticker"],
                weight_percent=r["weight_percent"],
                rationale=r["rationale"],
                relevance_score=relevance.get(r["ticker"], {}).get("relevance_score"),
                price_at_buy=r["price"],
            )
        )
    db.commit()

    return {"theme_key": theme_key, "status": status, "picks": len(ranked), "quality_score": quality_score}


def promote_theme_suggestion(theme_key: str, db: DbSession) -> dict:
    """Adopts the current candidate as live: re-stamps price_at_buy at
    today's prices (not whatever price was live when the candidate was
    generated, which could be stale by the time someone actually clicks
    "Update theme"), so since-buy tracking starts fresh from the moment
    of adoption, not from the cron run.

    The outgoing 'live' row is archived, not deleted - see
    get_theme_performance, which stitches every archived version plus
    the current live one into one continuous P/L history."""
    candidate = _get_suggestion(db, theme_key, "candidate")
    if candidate is None:
        raise ValueError(f"No candidate suggestion to promote for theme {theme_key!r}")

    tickers = [p.ticker for p in candidate.picks]
    fresh_prices = _fetch_current_prices(tickers)

    retired_at = _now()
    for old_live in db.query(ThemeSuggestion).filter(ThemeSuggestion.theme_key == theme_key, ThemeSuggestion.status == "live"):
        old_live.status = "archived"
        old_live.retired_at = retired_at
    candidate.status = "live"
    candidate.promoted_at = retired_at
    for pick in candidate.picks:
        price = fresh_prices.get(pick.ticker)
        if price is not None:
            pick.price_at_buy = price
    db.commit()

    return {"theme_key": theme_key, "promoted_picks": len(candidate.picks)}


def _diff_suggestions(live: ThemeSuggestion, candidate: ThemeSuggestion) -> dict:
    live_by_ticker = {p.ticker: p.weight_percent for p in live.picks}
    candidate_by_ticker = {p.ticker: p.weight_percent for p in candidate.picks}
    added = sorted(set(candidate_by_ticker) - set(live_by_ticker))
    removed = sorted(set(live_by_ticker) - set(candidate_by_ticker))
    reweighted = [
        {"ticker": t, "from": live_by_ticker[t], "to": candidate_by_ticker[t]}
        for t in sorted(set(live_by_ticker) & set(candidate_by_ticker))
        if abs(live_by_ticker[t] - candidate_by_ticker[t]) >= 1.0
    ]
    return {
        "added": added,
        "removed": removed,
        "reweighted": reweighted,
        "quality_delta": (
            round(candidate.quality_score - live.quality_score, 3)
            if candidate.quality_score is not None and live.quality_score is not None
            else None
        ),
    }


def _fetch_eps(tickers: list[str]) -> dict[str, float | None]:
    if not tickers:
        return {}

    def _fetch(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, get_eps(ticker)
        except Exception:
            return ticker, None

    return dict(parallel_map(_fetch, tickers))


def _fetch_volatility(tickers: list[str]) -> dict[str, float | None]:
    if not tickers:
        return {}

    def _fetch(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, get_annualized_volatility(ticker)
        except Exception:
            return ticker, None

    return dict(parallel_map(_fetch, tickers))


def _weighted_risk_metrics(
    picks: list[dict], eps_by_ticker: dict[str, float | None], vol_by_ticker: dict[str, float | None]
) -> dict:
    """Volatility: a weight-averaged annualized volatility across the
    theme's picks - "the magnitude and frequency of change in the
    securities' values, as weighted in the theme" - renormalized over
    just the picks with data (a missing ticker shouldn't silently drag
    the average toward zero). Valuation: an aggregate P/E - the sum of
    each pick's weighted price divided by the sum of its weighted EPS,
    the same index-style method (not an average of individual P/E
    ratios) real indices use so one extreme P/E doesn't dominate; picks
    with no or negative EPS are excluded from both sums since a negative
    P/E isn't a meaningful valuation signal."""
    weighted_vol = 0.0
    vol_weight_total = 0.0
    weighted_price = 0.0
    weighted_eps = 0.0
    for p in picks:
        weight = p["weight_percent"] / 100
        vol = vol_by_ticker.get(p["ticker"])
        if vol is not None:
            weighted_vol += weight * vol
            vol_weight_total += weight

        eps = eps_by_ticker.get(p["ticker"])
        price = p["current_price"] or p["price_at_buy"]
        if eps is not None and eps > 0 and price is not None:
            weighted_price += weight * price
            weighted_eps += weight * eps

    return {
        "volatility": round(weighted_vol / vol_weight_total, 4) if vol_weight_total else None,
        "valuation": round(weighted_price / weighted_eps, 2) if weighted_eps else None,
    }


# A fixed, equal-weighted basket of large, sector-diverse names standing
# in for "a typical large-cap stock" - deliberately not SPY/the S&P 500
# index itself. An index's own realized return volatility is structurally
# lower than any individual stock's (that's diversification working as
# intended across 500 holdings), so comparing a theme's 10-25-stock
# basket against the *index's* volatility would call every theme "high"
# regardless of what it actually holds - the two numbers aren't the same
# kind of thing. This basket lets _weighted_risk_metrics compute the
# benchmark the exact same way (weight-averaged across individual
# stocks) as it computes a theme's own numbers, so the comparison is
# apples-to-apples.
_RISK_BENCHMARK_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
    "JPM", "JNJ", "PG", "XOM", "UNH", "V", "HD", "KO", "DIS",
]


def _benchmark_risk_metrics() -> dict:
    """The "market" side of the Low/Moderate/High call - see
    _RISK_BENCHMARK_TICKERS for why this is a fixed mega-cap basket
    rather than the S&P 500 index itself."""
    tickers = _RISK_BENCHMARK_TICKERS
    equal_weight = 100 / len(tickers)
    current_prices = _fetch_current_prices(tickers)
    picks = [
        {"ticker": t, "weight_percent": equal_weight, "current_price": current_prices.get(t), "price_at_buy": None}
        for t in tickers
    ]
    return _weighted_risk_metrics(picks, _fetch_eps(tickers), _fetch_volatility(tickers))


_RISK_LABEL_LOW_MAX = 0.85
_RISK_LABEL_HIGH_MIN = 1.25


def _risk_label(value: float | None, benchmark_value: float | None) -> str | None:
    """Low/Moderate/High relative to the S&P 500's own value for the same
    metric, not a fixed absolute cutoff - a theme within 15% of the
    market's own volatility/valuation reads as "moderate" either way."""
    if value is None or not benchmark_value:
        return None
    ratio = value / benchmark_value
    if ratio < _RISK_LABEL_LOW_MAX:
        return "low"
    if ratio > _RISK_LABEL_HIGH_MIN:
        return "high"
    return "moderate"


def get_theme_suggestion(theme_key: str, db: DbSession) -> dict | None:
    """What the Themes tab actually reads: the live suggestion (with
    current prices/since-buy computed in), plus a diff against the
    pending candidate if a cron run has produced one. Returns None if
    refresh_theme_suggestion has never run for this theme - the frontend
    shows a placeholder for that case rather than falling back to a live
    build, since there's deliberately no more per-request build path."""
    live = _get_suggestion(db, theme_key, "live")
    if live is None:
        return None

    current_prices = _fetch_current_prices(sorted({p.ticker for p in live.picks}))
    sectors = _fetch_sectors(sorted({p.ticker for p in live.picks}))
    picks = []
    for p in live.picks:
        current_price = current_prices.get(p.ticker)
        change_percent = (
            round((current_price - p.price_at_buy) / p.price_at_buy * 100, 2)
            if current_price and p.price_at_buy
            else None
        )
        picks.append(
            {
                "ticker": p.ticker,
                "sector": sectors.get(p.ticker, "Other"),
                "weight_percent": p.weight_percent,
                "rationale": p.rationale,
                "relevance_score": p.relevance_score,
                "price_at_buy": p.price_at_buy,
                "current_price": current_price,
                "change_percent": change_percent,
            }
        )

    candidate = _get_suggestion(db, theme_key, "candidate")
    candidate_summary = None
    if candidate is not None:
        candidate_summary = {
            "generated_at": candidate.generated_at.isoformat(),
            "summary": candidate.summary,
            "quality_score": candidate.quality_score,
            **_diff_suggestions(live, candidate),
        }

    tickers = sorted({p.ticker for p in live.picks})
    risk_metrics = _weighted_risk_metrics(picks, _fetch_eps(tickers), _fetch_volatility(tickers))
    benchmark_metrics = _benchmark_risk_metrics()
    risk_metrics["volatility_label"] = _risk_label(risk_metrics["volatility"], benchmark_metrics["volatility"])
    risk_metrics["valuation_label"] = _risk_label(risk_metrics["valuation"], benchmark_metrics["valuation"])

    return {
        "theme_key": theme_key,
        "summary": live.summary,
        "quality_score": live.quality_score,
        "generated_at": live.generated_at.isoformat(),
        "promoted_at": live.promoted_at.isoformat() if live.promoted_at else None,
        "picks": picks,
        "candidate": candidate_summary,
        **risk_metrics,
    }


def _closes_from(ticker: str, start: date) -> pd.Series | None:
    """Real daily closes from `start` to today, date-indexed (tz dropped -
    yfinance's intraday tz varies by exchange, and every version's tickers
    need to align on the same plain-date index to sum across them). None
    if yfinance has nothing for this ticker/range, same as track_record.py's
    _closes_since - a ticker with no data (or a transient fetch failure,
    e.g. a rate limit) just drops out of that day's weighted sum rather
    than raising and taking down the whole computation."""
    try:
        history = with_yf_retries(lambda: yf.Ticker(ticker).history(start=start))
    except Exception:
        return None
    if history.empty:
        return None
    closes = history["Close"]
    closes.index = closes.index.date
    return closes


def _intraday_closes_from(ticker: str) -> pd.Series | None:
    """5-minute closes for today's session, timestamp-indexed (tz dropped -
    exchange-local wall-clock, same reasoning as _closes_from). Only used
    as a same-day fallback (see _version_return_index) for a theme
    promoted too recently to have even two daily closes yet - without
    this, a theme that's an hour old has exactly one daily data point and
    the chart has nothing to draw a line between."""
    try:
        history = with_yf_retries(lambda: yf.Ticker(ticker).history(period="1d", interval="5m"))
    except Exception:
        return None
    if history.empty:
        return None
    closes = history["Close"]
    closes.index = closes.index.tz_localize(None)
    return closes


def _intraday_version_return_index(picks: list[ThemeSuggestionPick]) -> pd.Series:
    weights = {p.ticker: p.weight_percent / 100 for p in picks}
    buy_prices = {p.ticker: p.price_at_buy for p in picks}

    def _fetch(ticker: str) -> tuple[str, pd.Series | None]:
        return ticker, _intraday_closes_from(ticker)

    series_by_ticker = {t: s for t, s in parallel_map(_fetch, list(weights)) if s is not None}
    if not series_by_ticker:
        return pd.Series(dtype=float)

    frame = pd.DataFrame(series_by_ticker).sort_index().ffill()
    normalized = frame.divide(pd.Series(buy_prices))
    weighted = normalized.multiply(pd.Series(weights))
    return weighted.sum(axis=1).dropna()


def _version_return_index(picks: list[ThemeSuggestionPick], start: date, end: date | None) -> pd.Series:
    """One suggestion version's daily weighted return index: for each
    trading day, Σ weight_percent/100 * (that day's close / price_at_buy)
    across its picks - starts near 1.0 on day one and moves with the
    basket's real performance from there. Forward-filled so a ticker
    missing a specific day (a data gap, not a holiday every ticker shares)
    doesn't zero out that day's sum."""
    weights = {p.ticker: p.weight_percent / 100 for p in picks}
    buy_prices = {p.ticker: p.price_at_buy for p in picks}

    def _fetch(ticker: str) -> tuple[str, pd.Series | None]:
        return ticker, _closes_from(ticker, start)

    series_by_ticker = {t: s for t, s in parallel_map(_fetch, list(weights)) if s is not None}
    if not series_by_ticker:
        return pd.Series(dtype=float)

    frame = pd.DataFrame(series_by_ticker).sort_index().ffill()
    if end is not None:
        frame = frame[frame.index <= end]
    normalized = frame.divide(pd.Series(buy_prices))
    weighted = normalized.multiply(pd.Series(weights))
    return weighted.sum(axis=1).dropna()


def _benchmark_series(point_dates: list[str], ticker: str = _BENCHMARK_TICKER) -> list[float | None]:
    """The benchmark's own return index (single ticker, no picks, no
    chain-linking across theme versions) resampled onto the theme's exact
    point dates - the "vs S&P 500" comparison line. Indexed to 100 at the
    theme's own first point so the two lines start together, not at
    SPY's own price history. None for a point the benchmark can't cover
    yet (before its own first close), left out of the response rather
    than zero-filled."""
    if not point_dates:
        return []

    has_intraday = any("T" in d for d in point_dates)
    first_day = date.fromisoformat(point_dates[0].split("T")[0])

    daily = _closes_from(ticker, first_day)
    if daily is None:
        return [None] * len(point_dates)
    daily = daily.sort_index()
    intraday = _intraday_closes_from(ticker) if has_intraday else None
    if intraday is not None:
        intraday = intraday.sort_index()

    base = float(daily.iloc[0])
    values: list[float | None] = []
    for d in point_dates:
        if "T" in d:
            ts = datetime.fromisoformat(d)
            matches = intraday.index[intraday.index <= ts] if intraday is not None else []
            price = float(intraday.loc[matches[-1]]) if len(matches) else None
        else:
            matches = daily.index[daily.index <= date.fromisoformat(d)]
            price = float(daily.loc[matches[-1]]) if len(matches) else None
        values.append(round(price / base * 100, 3) if price is not None else None)
    return values


def get_theme_performance(theme_key: str, db: DbSession) -> dict:
    """Reconstructs a theme's full profit/loss history from real
    historical closes, not a stored snapshot - one version at a time
    (every archived version plus the current live one, oldest first),
    chain-linked so an "Update theme" ticker swap shows as a continuation
    of cumulative return instead of resetting to zero, the same
    convention a rebalanced index's return series follows. `updates`
    marks each version's start date - the first entry is the theme's
    original buy-in, not an "update," so a caller rendering divider lines
    should skip index 0. Each point also carries a `benchmark` value - the
    S&P 500 (SPY), indexed to 100 at the same starting point, for an
    apples-to-apples "vs the market" comparison line."""
    versions = (
        db.query(ThemeSuggestion)
        .filter(
            ThemeSuggestion.theme_key == theme_key,
            ThemeSuggestion.status.in_(["live", "archived"]),
            ThemeSuggestion.promoted_at.isnot(None),
        )
        .order_by(ThemeSuggestion.promoted_at.asc())
        .all()
    )
    if not versions:
        return {"theme_key": theme_key, "points": [], "updates": []}

    points: list[dict] = []
    updates: list[dict] = []
    cursor_level = 100.0  # indexed to 100 at the start, like a normal total-return index, not a raw 1.0 multiplier
    for i, version in enumerate(versions):
        start = version.promoted_at.date()
        end = version.retired_at.date() if version.retired_at else None
        series = _version_return_index(version.picks, start, end)
        # A theme promoted today has at most one daily close so far - not
        # enough to draw a line. Only worth the extra intraday fetch for
        # the current, still-live version (older/retired versions have
        # had time to accumulate real daily history by now).
        is_current_and_fresh = i == len(versions) - 1 and version.retired_at is None and start == date.today()
        if len(series) < 2 and is_current_and_fresh:
            intraday = _intraday_version_return_index(version.picks)
            if len(intraday) >= 2:
                series = intraday
        if series.empty:
            continue
        scaled = series / series.iloc[0] * cursor_level
        new_points = [{"date": d.isoformat(), "value": round(float(v), 3)} for d, v in scaled.items()]
        # A version's retired_at and the next one's promoted_at are often
        # the same calendar day (that's the promotion moment) - drop the
        # duplicate x-axis point rather than showing the same date twice.
        if points and new_points and new_points[0]["date"] == points[-1]["date"]:
            new_points = new_points[1:]
        points.extend(new_points)
        cursor_level = float(scaled.iloc[-1])
        updates.append({"date": start.isoformat(), "tickers": sorted(p.ticker for p in version.picks)})

    benchmark_values = _benchmark_series([p["date"] for p in points])
    for point, benchmark_value in zip(points, benchmark_values):
        point["benchmark"] = benchmark_value

    return {"theme_key": theme_key, "points": points, "updates": updates}


def _fetch_day_changes(tickers: list[str]) -> dict[str, float | None]:
    if not tickers:
        return {}

    def _fetch(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, get_day_change(ticker)["percent"]
        except Exception:
            return ticker, None

    return dict(parallel_map(_fetch, tickers))


def _fetch_price_performance(tickers: list[str]) -> dict[str, dict | None]:
    if not tickers:
        return {}

    def _fetch(ticker: str) -> tuple[str, dict | None]:
        try:
            return ticker, get_price_performance(ticker)
        except Exception:
            return ticker, None

    return dict(parallel_map(_fetch, tickers))


def _weighted_average(picks: list[dict], value_by_ticker: dict[str, float | None]) -> float | None:
    """Weight-averaged value across picks, renormalized over just the
    picks with data - same "don't let a missing ticker drag the average
    toward zero" convention as _weighted_risk_metrics."""
    total = 0.0
    weight_total = 0.0
    for p in picks:
        value = value_by_ticker.get(p["ticker"])
        if value is None:
            continue
        weight = p["weight_percent"] / 100
        total += weight * value
        weight_total += weight
    return round(total / weight_total, 2) if weight_total else None




def _theme_summary_row(
    theme_key: str,
    live: ThemeSuggestion,
    db: DbSession,
    current_prices: dict[str, float | None],
    day_changes: dict[str, float | None],
    one_month_by_ticker: dict[str, float | None],
    one_year_by_ticker: dict[str, float | None],
    eps_by_ticker: dict[str, float | None],
    vol_by_ticker: dict[str, float | None],
    benchmark_metrics: dict,
) -> dict:
    tickers = sorted({p.ticker for p in live.picks})
    weight_by_ticker = {p.ticker: p.weight_percent for p in live.picks}
    top_tickers = [p.ticker for p in sorted(live.picks, key=lambda p: p.weight_percent, reverse=True)]

    picks_for_metrics = [
        {"ticker": t, "weight_percent": weight_by_ticker[t], "current_price": current_prices.get(t), "price_at_buy": None}
        for t in tickers
    ]
    risk_metrics = _weighted_risk_metrics(picks_for_metrics, eps_by_ticker, vol_by_ticker)

    performance_history = get_theme_performance(theme_key, db)
    since_inception = (
        round(performance_history["points"][-1]["value"] - 100, 2) if performance_history["points"] else None
    )
    inception_date = performance_history["points"][0]["date"].split("T")[0] if performance_history["points"] else None

    return {
        "key": theme_key,
        "stock_count": len(tickers),
        "preview_tickers": top_tickers[:5],
        "inception_date": inception_date,
        "day_change_percent": _weighted_average(picks_for_metrics, day_changes),
        "one_month_return_percent": _weighted_average(picks_for_metrics, one_month_by_ticker),
        "one_year_return_percent": _weighted_average(picks_for_metrics, one_year_by_ticker),
        "since_inception_percent": since_inception,
        "volatility_label": _risk_label(risk_metrics["volatility"], benchmark_metrics["volatility"]),
        "valuation_label": _risk_label(risk_metrics["valuation"], benchmark_metrics["valuation"]),
    }


def _empty_summary_row(theme_key: str) -> dict:
    return {
        "key": theme_key,
        "stock_count": 0,
        "preview_tickers": [],
        "inception_date": None,
        "day_change_percent": None,
        "one_month_return_percent": None,
        "one_year_return_percent": None,
        "since_inception_percent": None,
        "volatility_label": None,
        "valuation_label": None,
        "updated_at": None,
    }


def refresh_theme_summaries(db: DbSession) -> list[dict]:
    """Recomputes every theme's /themes-list-page row and upserts it into
    theme_summaries - stock count + a top-5 ticker preview, day/1-month/
    1-year/since-inception returns, and Low/Moderate/High volatility &
    valuation. Meant to run on a schedule (agents/refresh_themes.py),
    NOT per page visit - get_theme_summaries below is what the API
    actually reads, and it's a plain DB read with zero yfinance calls.

    Every per-ticker fetch (price, day change, 1mo/1yr return, EPS,
    volatility) still runs once for the *union* of tickers across every
    theme rather than once per theme - a lot of tickers repeat across
    baskets (MSFT, NVDA, AMZN...) - since this is real yfinance volume
    regardless of who triggers it or how often."""
    live_by_key = {theme["key"]: _get_suggestion(db, theme["key"], "live") for theme in THEME_CATALOG}
    all_tickers = sorted({p.ticker for live in live_by_key.values() if live is not None for p in live.picks})

    current_prices = _fetch_current_prices(all_tickers)
    day_changes = _fetch_day_changes(all_tickers)
    performance = _fetch_price_performance(all_tickers)
    eps_by_ticker = _fetch_eps(all_tickers)
    vol_by_ticker = _fetch_volatility(all_tickers)
    benchmark_metrics = _benchmark_risk_metrics()

    one_month_by_ticker = {t: (performance[t]["1_month"] if performance.get(t) else None) for t in all_tickers}
    one_year_by_ticker = {t: (performance[t]["1_year"] if performance.get(t) else None) for t in all_tickers}

    rows = []
    for theme in THEME_CATALOG:
        live = live_by_key[theme["key"]]
        if live is None:
            rows.append(_empty_summary_row(theme["key"]))
            continue
        # One theme's row failing outright (as opposed to just missing a
        # metric, which the _fetch_* helpers already degrade gracefully)
        # shouldn't blank out the other 23 - same "isolate the failure"
        # principle as every per-ticker fetch above, just at the per-theme
        # level instead.
        try:
            rows.append(
                _theme_summary_row(
                    theme["key"],
                    live,
                    db,
                    current_prices,
                    day_changes,
                    one_month_by_ticker,
                    one_year_by_ticker,
                    eps_by_ticker,
                    vol_by_ticker,
                    benchmark_metrics,
                )
            )
        except Exception:
            rows.append(_empty_summary_row(theme["key"]))

    for row in rows:
        inception_date = date.fromisoformat(row["inception_date"]) if row["inception_date"] else None
        existing = db.get(ThemeSummary, row["key"])
        if existing is None:
            existing = ThemeSummary(theme_key=row["key"])
            db.add(existing)
        existing.stock_count = row["stock_count"]
        existing.preview_tickers = ",".join(row["preview_tickers"])
        existing.inception_date = inception_date
        existing.day_change_percent = row["day_change_percent"]
        existing.one_month_return_percent = row["one_month_return_percent"]
        existing.one_year_return_percent = row["one_year_return_percent"]
        existing.since_inception_percent = row["since_inception_percent"]
        existing.volatility_label = row["volatility_label"]
        existing.valuation_label = row["valuation_label"]
        existing.updated_at = _now()
    db.commit()

    return rows


def get_theme_summaries(db: DbSession) -> list[dict]:
    """What the /themes list page actually reads - the last
    refresh_theme_summaries snapshot for every theme, straight from the
    DB. No yfinance calls here at all, so a page visit (however many
    people, however often) can never be what trips a rate limit - only
    the scheduled refresh can. A theme with no row yet (refresh hasn't
    run since it was added to the catalog) gets an empty row rather than
    being omitted, so it still shows up in the list."""
    rows_by_key = {row.theme_key: row for row in db.query(ThemeSummary).all()}
    summaries = []
    for theme in THEME_CATALOG:
        row = rows_by_key.get(theme["key"])
        if row is None:
            summaries.append(_empty_summary_row(theme["key"]))
            continue
        summaries.append(
            {
                "key": row.theme_key,
                "stock_count": row.stock_count,
                "preview_tickers": row.preview_tickers.split(",") if row.preview_tickers else [],
                "inception_date": row.inception_date.isoformat() if row.inception_date else None,
                "day_change_percent": row.day_change_percent,
                "one_month_return_percent": row.one_month_return_percent,
                "one_year_return_percent": row.one_year_return_percent,
                "since_inception_percent": row.since_inception_percent,
                "volatility_label": row.volatility_label,
                "valuation_label": row.valuation_label,
                "updated_at": row.updated_at.isoformat(),
            }
        )
    return summaries


def _main() -> None:
    from core.db import SessionLocal

    parser = argparse.ArgumentParser(description="Refresh a theme's shared model-portfolio suggestion")
    parser.add_argument("theme_key")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = refresh_theme_suggestion(args.theme_key, db)
    finally:
        db.close()
    print(result)


if __name__ == "__main__":
    _main()
