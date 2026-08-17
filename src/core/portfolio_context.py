"""Builds portfolio context for the Stock Team's Portfolio Fit specialist and
for making the synthesizer's verdict ownership-aware - sector/weight
concentration text plus a structured is_held flag, assembled from the same
SnapTrade positions data the Brokerage page shows. Kept separate from
routers/brokerage.py's response models since this is prompt text handed to
an agent, not an API response shape.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession

import core.snaptrade_client as snaptrade
from core.models_db import BrokerageAccount, BrokerageConnection
from core.tools import get_ticker_stats


@dataclass
class PortfolioContext:
    summary: str
    is_held: bool


def _active_accounts(db: DbSession, user_id: int) -> list[BrokerageAccount]:
    return (
        db.query(BrokerageAccount)
        .join(BrokerageConnection)
        .filter(BrokerageConnection.user_id == user_id, BrokerageConnection.status == "active")
        .all()
    )


def _sector_of(symbol: str) -> str:
    try:
        return get_ticker_stats(symbol).get("sector") or "Unknown"
    except ValueError:
        return "Unknown"


def build_portfolio_context(db: DbSession, user_id: int, ticker: str) -> PortfolioContext | None:
    """None if there's no active brokerage connection at all - ownership is
    genuinely unknown then, distinct from "connected and confirmed not
    held" (is_held=False)."""
    accounts = _active_accounts(db, user_id)
    if not accounts:
        return None

    value_by_symbol: dict[str, float] = {}
    for account in accounts:
        for position in snaptrade.get_account_positions(account.snaptrade_account_id):
            value_by_symbol[position["symbol"]] = (
                value_by_symbol.get(position["symbol"], 0.0) + position["units"] * position["price"]
            )

    if not value_by_symbol:
        return PortfolioContext(
            summary="The user's brokerage is connected but currently holds no positions (100% cash).",
            is_held=False,
        )

    total_value = sum(value_by_symbol.values())

    sector_value: dict[str, float] = {}
    for symbol, value in value_by_symbol.items():
        sector = _sector_of(symbol)
        sector_value[sector] = sector_value.get(sector, 0.0) + value

    top_holdings = sorted(value_by_symbol.items(), key=lambda kv: kv[1], reverse=True)[:8]
    holdings_lines = "\n".join(f"- {symbol}: {value / total_value * 100:.1f}% of portfolio" for symbol, value in top_holdings)

    sector_lines = "\n".join(
        f"- {sector}: {value / total_value * 100:.1f}%"
        for sector, value in sorted(sector_value.items(), key=lambda kv: kv[1], reverse=True)
    )

    ticker_sector = _sector_of(ticker)
    existing_weight = value_by_symbol.get(ticker, 0.0) / total_value * 100
    is_held = existing_weight > 0
    ticker_line = f"{ticker} is in the {ticker_sector} sector and is " + (
        f"already {existing_weight:.1f}% of the portfolio." if is_held else "not currently held."
    )

    summary = (
        f"Portfolio total value: ${total_value:,.0f}\n"
        f"Top holdings by weight:\n{holdings_lines}\n"
        f"Sector weights:\n{sector_lines}\n"
        f"{ticker_line}"
    )
    return PortfolioContext(summary=summary, is_held=is_held)
