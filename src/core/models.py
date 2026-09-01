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


class SpecialistFinding(BaseModel):
    signal: Literal["positive", "neutral", "negative"] = Field(
        description="Overall lean implied by this specialist's analysis of the ticker"
    )
    headline: str = Field(description="One short sentence (under ~12 words) naming the core takeaway")
    key_points: list[str] = Field(
        description="2-4 short bullet points (under ~15 words each) citing concrete figures from the "
        "specialist's tools, not restating the headline"
    )


class ThemeAllocationPick(BaseModel):
    ticker: str = Field(description="Stock ticker symbol, e.g. AAPL")
    weight_percent: float = Field(
        description="Percent of the total amount allocated to this ticker; all picks' weights sum to 100"
    )
    rationale: str = Field(
        description="One sentence tying this weight to the ticker's verdict, conviction, and predicted upside"
    )


class ThemeRelevanceScore(BaseModel):
    score: float = Field(
        description="0.0-1.0 relevance of this company's business to the theme, based on the matched "
        "10-K excerpt(s) - 1.0 means the theme is core to how the company makes money, 0.0 means the "
        "keyword match is coincidental/unrelated"
    )
    rationale: str = Field(description="One sentence citing what in the filing justifies the score")

    @field_validator("score")
    @classmethod
    def _clamp_score(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class ThemeAllocation(BaseModel):
    picks: list[ThemeAllocationPick] = Field(description="One entry per stock included in the basket")
    summary: str = Field(
        description="One or two sentences on the basket's overall tilt and its main concentration/risk caveat"
    )


class TeamVerdict(BaseModel):
    ticker: str = Field(description="Stock ticker symbol, e.g. AAPL")
    verdict: Literal["buy", "hold", "sell"] = Field(
        description="Overall recommendation weighing all specialists' findings"
    )
    key_factors: list[str] = Field(
        description="3-6 short bullet points, one per specialist consulted, naming the specialist and "
        "its finding (e.g. 'Valuation: cheaper than peers on trailing P/E')"
    )
    reasoning: str = Field(description="One or two closing sentences tying the key factors into the verdict")
    predicted_price: float = Field(
        description="A specific target price for the ticker at the end of predicted_horizon, consistent "
        "with the verdict and the specialists' findings (e.g. above current price for a buy)"
    )
    predicted_horizon: Literal["1w", "1mo", "3mo"] = Field(
        description="Timeframe the predicted_price target is for - 1 week, 1 month, or 3 months out. "
        "Matches the track record's scoring horizons so the prediction can be checked later."
    )
