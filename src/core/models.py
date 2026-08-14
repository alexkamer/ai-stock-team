"""Pydantic output models shared across the app (and reused by lessons)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CompanySnapshot(BaseModel):
    ticker: str = Field(description="Stock ticker symbol, e.g. AAPL")
    ticker_price: float = Field(description="Stock ticker current price, from the get_stock_price tool")
    market_cap: float = Field(description="Market capitalization in dollars, from the get_market_cap tool")
    pe_ratio: float = Field(description="Trailing P/E ratio, from the get_pe_ratio tool")
    company_name: str
    sentiment: Literal["bullish", "bearish", "neutral"] = Field(
        description="Based on the tone of recent headlines from the get_news_headlines tool"
    )
    summary: str = Field(description="One or two sentence summary of the company's current situation")

    @field_validator("ticker_price", "market_cap")
    @classmethod
    def must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(f"must be positive, got {value}")
        return value


class SentimentSummary(BaseModel):
    sentiment: Literal["bullish", "bearish", "neutral"] = Field(
        description="Based on the tone of the given recent headlines"
    )
    summary: str = Field(description="One or two sentence summary of the company's current situation")


class ArticleSummary(BaseModel):
    summary: str = Field(description="Two or three sentence summary of the article's content")
    looks_paywalled: bool = Field(description="Whether the scraped text appeared to be cut off/gated")


class PortfolioDigest(BaseModel):
    headline: str = Field(description="Short newspaper-style headline capturing today's overall portfolio move")
    article: str = Field(
        description="Multi-paragraph in-depth article (plain text, paragraphs separated by a blank line, "
        "no leading headline) analyzing how the portfolio performed today and why, grounded only in the "
        "holdings performance and news provided"
    )
    key_drivers: list[str] = Field(
        description="3-6 bullet points naming the specific holdings/news that drove today's performance"
    )
    watch_items: list[str] = Field(
        description="3-5 bullet points on what to watch going forward - upcoming catalysts, unresolved "
        "news threads, concentration or other risks"
    )


class TeamVerdict(BaseModel):
    ticker: str = Field(description="Stock ticker symbol, e.g. AAPL")
    verdict: Literal["buy", "hold", "sell"] = Field(
        description="Overall recommendation weighing both fundamentals and sentiment"
    )
    reasoning: str = Field(description="Brief explanation of the verdict, citing both specialists' findings")
