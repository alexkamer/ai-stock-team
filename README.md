# AI Stock Team

An AI-powered stock research app built with [pydantic-ai](https://ai.pydantic.dev/) and [yfinance](https://github.com/ranaroussi/yfinance), running on Claude via AWS Bedrock. It ships as a one-shot CLI, a FastAPI backend, and a React web app.

## What's here

- **CLI** — point it at a ticker, get a structured snapshot: price, market cap, P/E, sentiment, and a short summary.
- **Web app** — a dashboard with an editable watchlist, market screens (stocks/options/private companies), a per-ticker detail page with an interactive price chart, a multi-agent buy/hold/sell verdict page, and a research chat with a live per-ticker canvas, follow-up suggestions, and side-by-side comparison.
- **Backend API** — FastAPI + Server-Sent Events, streaming quotes, sentiment, and agent tool calls live to the frontend.

## Tech stack

| | |
|---|---|
| Agents | [pydantic-ai](https://ai.pydantic.dev/) on AWS Bedrock (Claude) |
| Data | [yfinance](https://github.com/ranaroussi/yfinance) |
| Backend | FastAPI, Uvicorn, Server-Sent Events |
| Frontend | React 19, React Router, Vite |
| Tests | pytest + pytest-asyncio |

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## Setup

This project calls Claude through AWS Bedrock, so you'll need AWS credentials with Bedrock access available in your shell (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`, or an equivalent bearer token setup). Region and model are configured in `src/core/config.yaml`.

```bash
uv sync --group main --group dev
```

## Running it

**CLI** — one-shot snapshot for a ticker:

```bash
uv run ai-stock-team NVDA
```

**Backend API** (serves the web app at `http://localhost:8000`):

```bash
uv run uvicorn core.api:app --app-dir src --reload
```

**Frontend** (in a separate terminal):

```bash
cd webapp
npm install
npm run dev
```

The Vite dev server proxies `/api` to the backend, so run both together while developing. Once both are up, open `http://localhost:5173`.

## Tour of the web app

**Dashboard (`/`)** — the landing page. A horizontally-scrolling strip of
major indices/commodities (S&P 500, Nasdaq, Dow, VIX, Gold, Bitcoin, Crude
Oil) up top, then a watchlist card with live prices, day-change badges, and
sparklines. Add a ticker with the input at the bottom of the watchlist (it's
validated against a real quote before it's added — a typo gets rejected
inline) and remove one by hovering a row and clicking the ×. Below that,
market-mover panels — Trending, Most Active, Top Gainers, Top Losers — each
linking through to a full paginated screen.

**Ticker Detail (`/tickers/AAPL`)** — click any ticker anywhere in the app to
land here. Streams in a price/market-cap/P/E header, an AI-generated
bullish/bearish/neutral sentiment badge with a short written summary, recent
headlines, and an interactive price chart (1D/5D/1mo/6mo/1y, line or
candlestick, with an optional SPY overlay for comparison) — choices persist
across visits.

**Stock Team Analysis (`/tickers/AAPL/team`)** — a multi-agent buy/hold/sell
verdict. A fundamentals specialist and a sentiment specialist each stream in
their own analysis card, then a synthesizer agent weighs both into a final
verdict with reasoning — so you see the "why" instead of just an answer.

**Research Chat (`/chat`)** — open-ended Q&A about any stock, backed by a
tool-using agent (price, market cap, P/E, day change, history, news,
watchlist lookups) with your watchlist and today's date in its system
prompt. A few things that go beyond a typical chatbot:
- **Research canvas** — every ticker you mention builds a live card on the
  right (price, day change, market cap, P/E, a real price-history
  sparkline), accumulating across the whole conversation instead of
  scrolling out of view. Ask about a ticker three different ways and it's
  still one card, filling in.
- **Compare** — check the "Compare" box on 2+ cards to get an aligned
  side-by-side stat table.
- **Suggested follow-ups** — quick-action chips for the obvious next
  questions (market cap, a different history window, recent news) based on
  what a card doesn't have yet.
- The conversation and canvas survive navigating away and even a page
  refresh (persisted to `localStorage`) — click a card to jump into Ticker
  Detail, then come back and the chat is still there.

**Markets (`/markets/...`)** — paginated screens for stocks (most-active,
gainers, losers, top-performing, trending, best-historical, top ETFs),
options (most-active, highest open interest), and private companies
(highest-valuation), reachable from the Dashboard's mover panels or the nav
bar.

## Tests

```bash
uv run pytest        # backend
cd webapp && npm test # frontend (Vitest)
```

## Project layout

```
src/
  agents/     # CLI entrypoint, chat agent, multi-agent stock team
  core/       # shared agent config, tools, FastAPI app, SSE helpers
webapp/       # React + Vite frontend
tests/        # pytest suite
```
