"""Cron entry point: refreshes every theme's suggestion in one pass.

    uv run python -m agents.refresh_themes            # ranking only, all themes - free
    uv run python -m agents.refresh_themes --filings   # + re-score filings-sourced themes first

Two schedules, one script, because the two steps have very different
costs: refresh_theme_suggestion (agents/theme_builder.py) is pure market
data - no LLM call, safe to run often. refresh_theme_filings_universe
(agents/theme_filings_scorer.py) is an LLM relevance-scoring pass over
SEC EDGAR hits - real dollars, and pointless to re-run more often than
filers actually re-file (10-Ks are ~quarterly at most). Suggested cron:

    0 6 * * 1       cd repo && uv run python -m agents.refresh_themes            # weekly
    0 6 1 * *       cd repo && uv run python -m agents.refresh_themes --filings  # monthly

Only `--filings` day runs the scorer, and only for themes with
`source == "filings"` - everything else always just re-ranks off
whatever universe (seed list, industry screen, or last filings run)
core.themes.get_theme_universe already resolves.

A per-theme failure (bad ticker data, EDGAR/Bedrock hiccup) is caught and
reported, not fatal - one theme's transient failure shouldn't block the
other seven from refreshing.
"""

import argparse
import asyncio

from core.db import SessionLocal
from core.themes import THEME_CATALOG
from agents.theme_builder import refresh_theme_suggestion
from agents.theme_filings_scorer import refresh_theme_filings_universe


async def refresh_all(include_filings: bool) -> list[dict]:
    db = SessionLocal()
    results = []
    try:
        for theme in THEME_CATALOG:
            key = theme["key"]
            entry = {"theme_key": key}
            try:
                if include_filings and theme["source"] == "filings":
                    entry["filings"] = await refresh_theme_filings_universe(key, db)
                entry["suggestion"] = refresh_theme_suggestion(key, db)
            except ValueError as e:
                entry["error"] = str(e)
            results.append(entry)
    finally:
        db.close()
    return results


def _main() -> None:
    parser = argparse.ArgumentParser(description="Refresh every theme's suggestion (see module docstring)")
    parser.add_argument("--filings", action="store_true", help="Also re-run the LLM filings scorer for filings-sourced themes")
    args = parser.parse_args()

    results = asyncio.run(refresh_all(args.filings))

    total_filings_cost = sum(r["filings"]["total_cost_usd"] for r in results if "filings" in r)
    for r in results:
        if "error" in r:
            print(f"{r['theme_key']}: FAILED - {r['error']}")
            continue
        line = f"{r['theme_key']}: {r['suggestion']['status']} ({r['suggestion']['picks']} picks)"
        if "filings" in r:
            line += f" | filings: {r['filings']['candidates_scored']} scored, ${r['filings']['total_cost_usd']:.4f}"
        print(line)
    if total_filings_cost:
        print(f"\nTotal filings-scoring cost this run: ${total_filings_cost:.4f}")


if __name__ == "__main__":
    _main()
