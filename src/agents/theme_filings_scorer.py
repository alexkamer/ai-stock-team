"""Builds a theme's ticker universe from what companies actually say in
their own 10-Ks, as an alternative to core/themes.py's hardcoded seed
lists (see THEME_CATALOG's `source: "filings"`).

Pipeline: EDGAR full-text search finds which filers' 10-Ks mention a
theme's keywords (core/edgar.py) -> filter to tickers with a real market
cap -> an LLM judges each candidate's relevance from its matched keywords
and company identity (a coincidental keyword hit isn't the same as the
theme being core to the business) -> top-scored tickers get persisted to
theme_filings_picks, replacing that theme's prior run.

This is a scheduled/manual job, not part of the live /themes/{key}/build
request path - it's meant to be re-run periodically (filings update at
most quarterly) via the CLI entry point at the bottom of this file, same
spirit as core/themes.py's _UNIVERSE_CACHE_TTL_SECONDS but persisted
instead of in-memory so it survives restarts.

Every scoring call is logged via log_llm_usage (real per-call cost, not
an estimate) so a run's total cost is known, not guessed - see
_run_summary's cost_usd.
"""

import argparse
import asyncio

from sqlalchemy.orm import Session as DbSession

from core.config import load_agent
from core.db import SessionLocal
from core.edgar import search_filings
from core.llm_usage import log_llm_usage
from core.models import ThemeRelevanceScore
from core.models_db import ThemeFilingsPick
from core.themes import get_theme
from core.tools import get_market_cap, parallel_map

_AGENT_RETRIES = 2
_MAX_LLM_CANDIDATES = 50  # bounds LLM spend per run regardless of how many EDGAR hits come back
_FINAL_UNIVERSE_LIMIT = 15
_MIN_MARKET_CAP = 2_000_000_000
_MIN_RELEVANCE_SCORE = 0.5  # below this, a keyword hit is boilerplate/peripheral, not the theme being core to the business

scorer_agent = load_agent(output_type=ThemeRelevanceScore, retries=_AGENT_RETRIES)


def _gather_candidates(keywords: list[str]) -> dict[str, dict]:
    """One EDGAR full-text search per keyword, aggregated by ticker so a
    company matching multiple keywords (stronger signal) surfaces above
    one matching a single keyword once."""
    candidates: dict[str, dict] = {}
    for keyword in keywords:
        for hit in search_filings(keyword):
            if not hit["ticker"]:
                continue
            entry = candidates.setdefault(
                hit["ticker"],
                {"company_name": hit["company_name"], "hit_count": 0, "max_score": 0.0, "matched_keywords": set()},
            )
            entry["hit_count"] += 1
            entry["max_score"] = max(entry["max_score"], hit["score"])
            entry["matched_keywords"].add(keyword)
    return candidates


def _min_max_normalize(values: list[float]) -> list[float]:
    """Scales values to [0, 1] within this candidate set - same idiom as
    theme_builder.py's version. Needed because EDGAR's max_score is a
    TF-IDF-style relevance score that rewards a short, keyword-dense
    filing over a mega-cap's long, diversified 10-K even when the theme
    is just as core to the mega-cap's business - so ranking candidates by
    raw max_score alone silently drops names like NVDA/MSFT before they
    ever reach the LLM. Blending normalized hit_count and max_score
    keeps a candidate that's strong on *either* signal, not just one."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _filter_by_market_cap(candidates: dict[str, dict]) -> dict[str, dict]:
    """Drops tickers EDGAR matched but that either aren't a real
    tradeable equity (funds, defunct filers) or fall under the theme's
    market-cap floor - same floor core/themes.py's industry screen uses."""
    tickers = list(candidates)

    def _fetch(ticker: str) -> float | None:
        try:
            return get_market_cap(ticker)
        except ValueError:
            return None

    market_caps = parallel_map(_fetch, tickers)
    kept = {}
    for ticker, market_cap in zip(tickers, market_caps):
        if market_cap is not None and market_cap >= _MIN_MARKET_CAP:
            kept[ticker] = {**candidates[ticker], "market_cap": market_cap}
    return kept


async def _score_candidate(theme: dict, ticker: str, candidate: dict, db: DbSession, user_id: int | None) -> dict:
    keywords = ", ".join(sorted(candidate["matched_keywords"]))
    result = await scorer_agent.run(
        f"Theme: {theme['name']} - {theme['description']}\n\n"
        f"Candidate: {candidate['company_name']} ({ticker}), market cap "
        f"${candidate['market_cap'] / 1e9:.1f}B.\n"
        f"Its 10-K filing(s) from the last ~13 months matched these theme keywords: {keywords} "
        f"({candidate['hit_count']} total keyword match(es) across its recent filings).\n\n"
        f"Score how central this theme is to {ticker}'s actual business, not just whether the "
        f"keywords appear - a passing mention in a risk-factors boilerplate section scores low even "
        f"with several hits."
    )
    cost_usd = log_llm_usage(db, user_id, "theme_filings_scorer", result.usage)
    return {
        "ticker": ticker,
        "company_name": candidate["company_name"],
        "market_cap": candidate["market_cap"],
        "relevance_score": result.output.score,
        "rationale": result.output.rationale,
        "cost_usd": cost_usd,
    }


def _row(theme_key: str, ticker: str, status: str, candidate: dict, scored: dict | None = None) -> ThemeFilingsPick:
    return ThemeFilingsPick(
        theme_key=theme_key,
        ticker=ticker,
        status=status,
        hit_count=candidate["hit_count"],
        matched_keywords=", ".join(sorted(candidate["matched_keywords"])),
        market_cap=candidate.get("market_cap"),
        relevance_score=scored["relevance_score"] if scored else None,
        rationale=scored["rationale"] if scored else None,
    )


async def refresh_theme_filings_universe(theme_key: str, db: DbSession, user_id: int | None = None) -> dict:
    """Runs the full pipeline for one theme and persists every candidate
    considered - not just the winners - as a full audit trail (see
    ThemeFilingsPick.status), replacing that theme's prior run wholesale.
    Returns a summary (picks + total LLM cost) rather than just the
    tickers, so a caller (e.g. the CLI below) can see what it cost
    without a separate llm_call_log query."""
    theme = get_theme(theme_key)
    keywords = theme.get("keywords")
    if not keywords:
        raise ValueError(f"Theme {theme_key!r} has no keywords - only filings-sourced themes can be scored")

    all_candidates = _gather_candidates(keywords)
    passed_market_cap = _filter_by_market_cap(all_candidates)
    dropped_market_cap = {t: c for t, c in all_candidates.items() if t not in passed_market_cap}

    tickers = list(passed_market_cap)
    hit_counts_norm = _min_max_normalize([passed_market_cap[t]["hit_count"] for t in tickers])
    scores_norm = _min_max_normalize([passed_market_cap[t]["max_score"] for t in tickers])
    blended = dict(zip(tickers, (h + s for h, s in zip(hit_counts_norm, scores_norm))))
    ranked = sorted(passed_market_cap.items(), key=lambda kv: blended[kv[0]], reverse=True)
    to_score, uncapped = ranked[:_MAX_LLM_CANDIDATES], ranked[_MAX_LLM_CANDIDATES:]

    scored = [await _score_candidate(theme, ticker, candidate, db, user_id) for ticker, candidate in to_score]
    scored.sort(key=lambda c: (c["relevance_score"], c["market_cap"]), reverse=True)
    relevant = [c for c in scored if c["relevance_score"] >= _MIN_RELEVANCE_SCORE]
    top_picks = relevant[:_FINAL_UNIVERSE_LIMIT]
    kept_tickers = {c["ticker"] for c in top_picks}

    db.query(ThemeFilingsPick).filter(ThemeFilingsPick.theme_key == theme_key).delete()
    for c in scored:
        status = "kept" if c["ticker"] in kept_tickers else "below_threshold"
        db.add(_row(theme_key, c["ticker"], status, passed_market_cap[c["ticker"]], c))
    for ticker, candidate in dropped_market_cap.items():
        db.add(_row(theme_key, ticker, "dropped_market_cap", candidate))
    for ticker, candidate in uncapped:
        db.add(_row(theme_key, ticker, "dropped_uncapped", candidate))
    db.commit()

    return {
        "theme_key": theme_key,
        "candidates_scored": len(scored),
        "candidates_seen": len(all_candidates),
        "total_cost_usd": round(sum(c["cost_usd"] for c in scored), 6),
        "picks": [{k: v for k, v in c.items() if k != "cost_usd"} for c in top_picks],
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description="Refresh a theme's filings-scored ticker universe")
    parser.add_argument("theme_key")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        summary = asyncio.run(refresh_theme_filings_universe(args.theme_key, db))
    finally:
        db.close()

    print(f"Scored {summary['candidates_scored']} candidates for {summary['theme_key']!r}")
    print(f"Total LLM cost: ${summary['total_cost_usd']:.4f}")
    for pick in summary["picks"]:
        print(f"  {pick['ticker']:<6} {pick['relevance_score']:.2f}  {pick['rationale']}")


if __name__ == "__main__":
    _main()
