"""Diagnostic: for a broad sample of market-news articles, try to scrape each
one's full text (via core.tools.scrape_article) and tally per-publisher
readable/paywalled/error rates.

Answers "which publishers can we actually read past the headline for?"
before building anything on top of scrape_article (paywall-aware ranking,
a publisher allowlist/denylist, etc.) - grounds that decision in real scrape
results instead of guessing from publisher reputation.

Run with: uv run python scripts/news_scrape_coverage.py
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.tools import get_market_news, parallel_map, scrape_article  # noqa: E402

# A sector-diverse sample rather than just mega-cap tech, since which
# publishers cover a story (and how aggressively they paywall it) varies by
# industry.
TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "JPM", "BAC", "XOM", "CVX", "UNH", "PFE", "WMT", "KO", "DIS", "BA", "CAT",
]
ARTICLE_LIMIT = 120


def try_scrape(article: dict) -> dict:
    try:
        result = scrape_article(article["url"])
        return {**article, **result, "error": None}
    except Exception as exc:  # noqa: BLE001 - every failure mode should be counted, not crash the run
        return {**article, "text": "", "word_count": 0, "looks_paywalled": None, "error": str(exc)}


def main() -> None:
    print(f"Fetching up to {ARTICLE_LIMIT} articles across {len(TICKERS)} tickers...")
    articles = get_market_news(TICKERS, limit=ARTICLE_LIMIT)
    print(f"Got {len(articles)} articles. Scraping each (this hits every publisher's site directly)...\n")

    results = parallel_map(try_scrape, articles)

    by_publisher = defaultdict(list)
    for r in results:
        by_publisher[r["publisher"] or "(unknown)"].append(r)

    rows = []
    for publisher, items in by_publisher.items():
        total = len(items)
        errored = sum(1 for i in items if i["error"])
        paywalled = sum(1 for i in items if i["looks_paywalled"])
        readable = total - errored - paywalled
        avg_words = sum(i["word_count"] for i in items) / total
        rows.append((publisher, total, readable, paywalled, errored, avg_words))

    rows.sort(key=lambda r: (-(r[2] / r[1]), -r[1]))

    header = f"{'Publisher':<28}{'N':>4}{'Readable':>10}{'Paywalled':>11}{'Errored':>9}{'AvgWords':>10}"
    print(header)
    print("-" * len(header))
    for publisher, total, readable, paywalled, errored, avg_words in rows:
        print(f"{publisher:<28}{total:>4}{readable:>10}{paywalled:>11}{errored:>9}{avg_words:>10.0f}")

    total_articles = len(results)
    if total_articles == 0:
        print("\nNo articles found.")
        return
    total_readable = sum(1 for r in results if not r["error"] and not r["looks_paywalled"])
    print(f"\nOverall: {total_readable}/{total_articles} articles fully readable ({total_readable / total_articles:.0%})")

    errors = [r for r in results if r["error"]]
    if errors:
        print(f"\nSample errors ({len(errors)} total):")
        for r in errors[:10]:
            print(f"  [{r['publisher']}] {r['url']}: {r['error']}")


if __name__ == "__main__":
    main()
