"""Thin wrapper around SEC EDGAR's full-text search API - lets a theme's
universe be sourced from what companies actually say in their own 10-Ks
(see agents/theme_filings_scorer.py) instead of a hand-picked list or a
single yfinance industry tag.

No API key needed, but SEC asks every caller to identify itself with a
real contact in the User-Agent header - replace _USER_AGENT below with
your own before running this against SEC's servers for real.
"""

import re
from datetime import date, timedelta

import requests

_USER_AGENT = "ai-stock-team theme research (contact@example.com)"
_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_TICKER_RE = re.compile(r"\(([A-Z]{1,6}(?:\.[A-Z])?)\)")

_TRAILING_DAYS = 400  # covers the most recent annual 10-K cycle for any filer


def search_filings(keyword: str, forms: str = "10-K", limit: int = 40) -> list[dict]:
    """Full-text-search every filer's `forms` filings from the last
    _TRAILING_DAYS for an exact phrase, ranked by SEC's own relevance
    score. Returns one entry per matching filing:
    {ticker, company_name, cik, score, file_date} - `ticker` is None if
    the filing's display name didn't contain a parenthesized ticker
    (foreign private issuers often file without one), so callers should
    drop those.
    """
    end = date.today()
    start = end - timedelta(days=_TRAILING_DAYS)
    response = requests.get(
        _SEARCH_URL,
        params={
            "q": f'"{keyword}"',
            "forms": forms,
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        },
        headers={"User-Agent": _USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    hits = response.json().get("hits", {}).get("hits", [])[:limit]

    results = []
    for hit in hits:
        source = hit["_source"]
        display_name = (source.get("display_names") or [""])[0]
        ticker_match = _TICKER_RE.search(display_name)
        results.append(
            {
                "ticker": ticker_match.group(1) if ticker_match else None,
                "company_name": display_name.split("(")[0].strip(),
                "cik": (source.get("ciks") or [None])[0],
                "score": hit.get("_score", 0.0),
                "file_date": source.get("file_date"),
            }
        )
    return results
