"""Compat shim so lessons/ (which do `sys.path.insert` to repo root, not src/)
keep working after the app code moved to src/core/.
"""

from core.tools import *  # noqa: F401,F403
from core.tools import (  # noqa: F401
    Watchlist,
    get_company_name,
    get_day_change,
    get_market_cap,
    get_news_headlines,
    get_pe_ratio,
    get_price_history,
    get_sparkline_prices,
    get_stock_price,
    get_watchlist_prices,
)
