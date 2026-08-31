"""Theme catalog for the Themes tab - a fixed, curated list of themes
rather than free-text/AI-invented ones, so the basket behind each theme is
predictable and reviewable (same spirit as NEWS_CATEGORY_TICKERS in
tools.py, just richer: a description + risk label alongside the tickers).

Each theme's *ticker universe* (get_theme_universe below), though, is not
always the static list in this file - themes that map cleanly to one
yfinance industry classification (source="industry") get their tickers
from a live screen instead, so the universe reflects the real market
(current constituents, current market caps) rather than a list I hand-
picked from memory - which is exactly how CYBR (delisted after Palo Alto's
acquisition of CyberArk) ended up stale in the first shipped version.
Themes that genuinely span multiple industries (source="seed") keep a
curated list, since there's no single yfinance industry to screen.
"""

from time import monotonic

from core.tools import get_stock_price, parallel_map, screen_by_industry

THEME_CATALOG = [
    {
        "key": "ai-machine-learning",
        "name": "AI & Machine Learning",
        "description": "Companies building the chips, cloud infrastructure, and software powering the AI boom.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "NVDA", "MSFT", "GOOGL", "META", "AMZN", "AMD", "AVGO", "PLTR",
            "SNOW", "CRM", "ORCL", "SMCI", "ANET", "NOW",
        ],
    },
    {
        "key": "clean-energy-ev",
        "name": "Clean Energy & EVs",
        "description": "Solar, battery, and electric-vehicle makers riding the shift away from fossil fuels.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "TSLA", "ENPH", "FSLR", "SEDG", "RUN", "PLUG", "NEE", "RIVN",
            "LCID", "ALB", "BE", "CHPT",
        ],
    },
    {
        "key": "cybersecurity",
        "name": "Cybersecurity",
        "description": "Security vendors protecting enterprises and governments from a growing attack surface.",
        "risk_level": "moderate",
        "source": "industry",
        "industry": "Software—Infrastructure",
    },
    {
        "key": "cloud-enterprise-software",
        "name": "Cloud & Enterprise Software",
        "description": "SaaS and cloud-infrastructure platforms that run the back office for other businesses.",
        "risk_level": "moderate",
        "source": "industry",
        "industry": "Software—Application",
    },
    {
        "key": "healthcare-innovation",
        "name": "Healthcare Innovation",
        "description": "Drugmakers, biotech, and medtech pushing into GLP-1s, gene therapy, and surgical robotics.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "LLY", "NVO", "UNH", "ISRG", "VRTX", "REGN", "DXCM", "ABBV", "MRNA", "PODD",
        ],
    },
    {
        "key": "semiconductors",
        "name": "Semiconductors",
        "description": "Chip designers, foundries, and equipment makers behind every AI and consumer device.",
        "risk_level": "higher",
        "source": "industry",
        "industry": "Semiconductors",
    },
    {
        "key": "fintech-digital-payments",
        "name": "Fintech & Digital Payments",
        "description": "Payment networks and digital-first financial platforms displacing cash and legacy banking.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "V", "MA", "PYPL", "SQ", "COIN", "SOFI", "AXP", "ADYEY", "FI", "GPN",
        ],
    },
    {
        "key": "consumer-ecommerce",
        "name": "Consumer & E-commerce",
        "description": "Online retail, marketplaces, and digital-first consumer brands.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "AMZN", "SHOP", "MELI", "ETSY", "CHWY", "ABNB", "BKNG", "SBUX", "NKE", "CMG",
        ],
    },
]

_THEMES_BY_KEY = {theme["key"]: theme for theme in THEME_CATALOG}

_UNIVERSE_LIMIT = 15
_MIN_MARKET_CAP = 2_000_000_000
_UNIVERSE_CACHE_TTL_SECONDS = 86_400  # a day - industry composition/prices don't shift intraday enough to rescreen every request
_universe_cache: dict[str, tuple[float, list[str]]] = {}


def get_theme(key: str) -> dict:
    """Look up a theme by its key, raising ValueError (not KeyError) for an
    unknown one - same convention as tools.py's get_stock_price/_quote, so
    callers can treat "bad input" uniformly across this codebase."""
    theme = _THEMES_BY_KEY.get(key)
    if theme is None:
        raise ValueError(f"Unknown theme key {key!r}")
    return theme


def _is_valid_ticker(ticker: str) -> bool:
    try:
        get_stock_price(ticker)
        return True
    except ValueError:
        return False


def get_theme_universe(theme_key: str) -> list[str]:
    """This theme's actual ticker universe: a live industry screen or the
    static seed list (per theme["source"]), filtered to tickers with a
    fetchable live price - the general fix for the CYBR problem, applied
    to every theme regardless of how its candidates were sourced. Cached
    per theme for _UNIVERSE_CACHE_TTL_SECONDS so repeat page loads don't
    re-run the screen/validity checks every time (same hand-rolled TTL
    pattern as tools.py's _info_cache)."""
    cached = _universe_cache.get(theme_key)
    if cached is not None and monotonic() - cached[0] < _UNIVERSE_CACHE_TTL_SECONDS:
        return cached[1]

    theme = get_theme(theme_key)
    if theme["source"] == "industry":
        candidates = screen_by_industry(theme["industry"], min_market_cap=_MIN_MARKET_CAP, limit=_UNIVERSE_LIMIT)
    else:
        candidates = theme["tickers"]

    valid = [ticker for ticker, ok in zip(candidates, parallel_map(_is_valid_ticker, candidates)) if ok]
    _universe_cache[theme_key] = (monotonic(), valid)
    return valid
