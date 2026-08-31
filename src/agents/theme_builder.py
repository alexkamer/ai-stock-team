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
"""

import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from core.config import load_agent
from core.models import ThemeAllocation
from core.models_db import ThemePortfolio, ThemePortfolioPick
from core.themes import get_theme
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

    return {
        "theme_key": theme_key,
        "amount": amount,
        "summary": summary,
        "picks": picks,
        "created_at": record.created_at.isoformat(),
    }


def build_formula_allocation(theme_key: str, amount: float, tickers: list[str], db: DbSession, user_id: int) -> dict:
    """No LLM call anywhere in this function - weights come from a plain
    momentum + market-cap composite score over live data, so this resolves
    in the time it takes to fetch a handful of yfinance fields, not the
    minutes a full multi-agent scan takes (see build_ai_allocation)."""
    if not tickers:
        return _empty_result(theme_key, amount, "No tickers in this theme's universe today - try again another day.")

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
        return _empty_result(theme_key, amount, "Couldn't fetch live data for this theme's tickers - try again later.")

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

    picks = []
    for ticker, weight_percent, rationale in normalized:
        dollar_amount = amount * weight_percent / 100.0
        picks.append(
            {
                "ticker": ticker,
                "verdict": None,
                "weight_percent": round(weight_percent, 2),
                "dollar_amount": round(dollar_amount, 2),
                "shares": round(dollar_amount / prices[ticker], 4),
                "rationale": rationale,
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
            }
        )

    return _persist(theme_key, amount, result.output.summary, picks, "ai_team", db, user_id)


def get_theme_history(db: DbSession, user_id: int) -> list[dict]:
    portfolios = (
        db.query(ThemePortfolio)
        .filter(ThemePortfolio.user_id == user_id)
        .order_by(ThemePortfolio.created_at.desc())
        .all()
    )
    return [
        {
            "theme_key": p.theme_key,
            "amount": p.amount,
            "summary": p.summary,
            "method": p.method,
            "created_at": p.created_at.isoformat(),
            "picks": [
                {
                    "ticker": pick.ticker,
                    "verdict": pick.verdict,
                    "weight_percent": pick.weight_percent,
                    "dollar_amount": pick.dollar_amount,
                    "shares": pick.shares,
                    "rationale": pick.rationale,
                }
                for pick in p.picks
            ],
        }
        for p in portfolios
    ]
