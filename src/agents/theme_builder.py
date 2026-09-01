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
from core.models_db import ThemePortfolio, ThemePortfolioPick, ThemeSuggestion, ThemeSuggestionPick, _now
from core.themes import get_filings_relevance, get_theme, get_theme_universe
from core.tools import get_market_cap, get_price_performance, get_stock_price, parallel_map

_AGENT_RETRIES = 3
_MIN_PICKS = 3
_MAX_WEIGHT_PERCENT = 35.0
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

    tickers = [r["ticker"] for r in usable]
    prices = dict(zip(tickers, parallel_map(get_stock_price, tickers)))

    candidates = _select_candidates(usable, prices)
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
        except ValueError:
            return ticker, None

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

    return {
        "theme_key": theme_key,
        "summary": live.summary,
        "quality_score": live.quality_score,
        "generated_at": live.generated_at.isoformat(),
        "promoted_at": live.promoted_at.isoformat() if live.promoted_at else None,
        "picks": picks,
        "candidate": candidate_summary,
    }


def _closes_from(ticker: str, start: date) -> pd.Series | None:
    """Real daily closes from `start` to today, date-indexed (tz dropped -
    yfinance's intraday tz varies by exchange, and every version's tickers
    need to align on the same plain-date index to sum across them). None
    if yfinance has nothing for this ticker/range, same as track_record.py's
    _closes_since - a ticker with no data just drops out of that day's
    weighted sum rather than raising."""
    history = yf.Ticker(ticker).history(start=start)
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
    history = yf.Ticker(ticker).history(period="1d", interval="5m")
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


def get_theme_performance(theme_key: str, db: DbSession) -> dict:
    """Reconstructs a theme's full profit/loss history from real
    historical closes, not a stored snapshot - one version at a time
    (every archived version plus the current live one, oldest first),
    chain-linked so an "Update theme" ticker swap shows as a continuation
    of cumulative return instead of resetting to zero, the same
    convention a rebalanced index's return series follows. `updates`
    marks each version's start date - the first entry is the theme's
    original buy-in, not an "update," so a caller rendering divider lines
    should skip index 0."""
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

    return {"theme_key": theme_key, "points": points, "updates": updates}


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
