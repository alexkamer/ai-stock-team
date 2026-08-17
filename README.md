# AI Stock Team

An AI-powered stock research app built with [pydantic-ai](https://ai.pydantic.dev/) and [yfinance](https://github.com/ranaroussi/yfinance), running on Claude via AWS Bedrock. It ships as a one-shot CLI, a FastAPI backend, and a React web app.

## What's here

- **CLI** — point it at a ticker, get a structured snapshot: price, market cap, P/E, sentiment, and a short summary.
- **Web app** — a dashboard with an editable watchlist, market screens (stocks/options/private companies), a per-ticker detail page with an interactive price chart, a multi-agent buy/hold/sell verdict page, a research chat with a live per-ticker canvas, follow-up suggestions, and side-by-side comparison, and a read-only brokerage page (via SnapTrade) with live positions/orders and news for what you actually hold.
- **Backend API** — FastAPI + Server-Sent Events, streaming quotes, sentiment, and agent tool calls live to the frontend.

## Tech stack

| | |
|---|---|
| Agents | [pydantic-ai](https://ai.pydantic.dev/) on AWS Bedrock (Claude) |
| Data | [yfinance](https://github.com/ranaroussi/yfinance) |
| Brokerage linking | [SnapTrade](https://snaptrade.com/) |
| Backend | FastAPI, Uvicorn, Server-Sent Events |
| Frontend | React 19, React Router, Vite |
| Tests | pytest + pytest-asyncio |

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## Setup

This project calls Claude through AWS Bedrock, so you'll need AWS credentials with Bedrock access available in your shell (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`, or an equivalent bearer token setup). Region and model are configured in `src/core/config.yaml`.

```bash
uv sync --group main --group dev
```

(Or `make install`, which also runs `npm install` in `webapp/` for you.)

Copy `.env.example` to `.env` and fill in whichever sections you need. The
brokerage page needs a `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY` pair
from your [SnapTrade dashboard](https://snaptrade.com/) — everything else in
the app works without it.

### Configuring the AI model

All agents (CLI, chat, stock team, Daily Digest) run on Claude via AWS
Bedrock, built centrally by `src/core/config.py` from `src/core/config.yaml`
— there's no separate key/model config per agent.

1. **AI keys** — get AWS credentials with Bedrock access (and access to
   whichever model you pick, granted per-region in the Bedrock console).
   Either export them in your shell:
   ```
   AWS_ACCESS_KEY_ID=
   AWS_SECRET_ACCESS_KEY=
   AWS_SESSION_TOKEN=
   ```
   or put them in `.env` — `core/env.py` loads it before anything reads
   `os.environ`, and `load_dotenv()` never overrides a variable already set
   in your real shell, so this is safe to add alongside existing AWS
   SSO/shared-credentials-file setups. If you're already logged in via
   `aws sso login` or similar, you can skip this — the app will pick up
   your ambient credentials.
2. **Model/region** — edit the `model:` and `provider:` sections of
   `src/core/config.yaml`:
   ```yaml
   provider:
     region_name: us-east-2   # must be a region where you have Bedrock access

   model:
     name: global.anthropic.claude-sonnet-5   # any Bedrock-hosted model ID
   ```
3. **Generation behavior** (optional) — `model_settings:` in the same file
   controls things like `max_tokens`, `temperature`, and `timeout`; see the
   comments in `config.yaml` for what each does and why a couple are
   commented out by default (e.g. `temperature` is rejected by
   `claude-sonnet-5` on Bedrock).

No code changes or restarts of anything but the backend are needed to swap
models — just edit `config.yaml` and restart `make backend`.

### Connecting SnapTrade

1. Sign up for a [SnapTrade](https://snaptrade.com/) developer account and
   create an app. On its API keys page, grab the **Client ID** and generate
   a **Personal API key** (its secret is the consumer key) — this app uses
   that single-identity Personal API key model, not SnapTrade's
   multi-tenant `registerUser`/`userId`/`userSecret` flow, so there's no
   per-app-user provisioning step.
2. Put those two values in `.env`:
   ```
   SNAPTRADE_CLIENT_ID=
   SNAPTRADE_CONSUMER_KEY=
   ```
3. Restart the backend, then open `/brokerage` in the web app and click
   **Connect a brokerage**. That opens SnapTrade's hosted Connection
   Portal — an OAuth-style flow where you pick your brokerage and log in
   directly with them; credentials never pass through this app.
4. Once you complete the flow you're redirected back and the connection
   shows up as a card with live positions, orders, and news.

The connection is deliberately read-only end-to-end: the portal is always
requested with `connection_type="read"` (see
`src/core/snaptrade_client.py`), and no trade-execution SDK calls are wired
up anywhere in the app, so there's no code path that could place a trade.
Positions/balances are fetched live on every page load and never persisted
— only which brokerage/account you've connected is stored.

The app has user accounts backed by a local SQLite DB. Set up the schema:

```bash
uv run alembic upgrade head
```

By default (`AUTH_REQUIRED=false`, or just unset) the brokerage page skips
login entirely — requests are transparently attributed to a single local
user, since a fork-and-run instance only ever has one person using it.
Login/signup only matter if you're hosting one instance for more than one
person; set `AUTH_REQUIRED=true` in `.env` to turn them back on, then seed a
standard admin account for testing:

```bash
uv run python -m core.seed_admin   # creates admin@example.com, prints/writes its password to .admin_credentials
```

`.admin_credentials` is gitignored — read it locally to get the admin
password; rerunning `seed_admin` is a no-op if the account already exists.

## Running it

**CLI** — one-shot snapshot for a ticker:

```bash
uv run ai-stock-team NVDA
```

**Backend API** (serves the web app at `http://localhost:8000`):

```bash
make backend
```

**Frontend** (in a separate terminal):

```bash
make frontend
```

Or run both at once with `make dev` (Ctrl-C stops both). The Vite dev
server proxies `/api` to the backend, so run both together while
developing. Once both are up, open `http://localhost:5173`.

## Tour of the web app

**Dashboard (`/`)** — the landing page. A horizontally-scrolling strip of
major indices/commodities (S&P 500, Nasdaq, Dow, VIX, Gold, Bitcoin, Crude
Oil) up top, then a news section: a featured-story carousel, a plain list of
the rest of your watchlist's headlines, three category columns (Top
Stories, Markets & Economy, Tech & AI), and a More News overflow section for
everything else. Articles are picked by editorial quality (Yahoo's editors'
pick flag and thumbnail presence) rather than pure recency, and each is
tagged with a "TICKER +1.23%" day-change badge where a source ticker is
known. This ranking (shared by every news surface in the app — Dashboard,
Ticker Detail, Brokerage) also collapses syndicated wire stories that show
up under more than one ticker's feed into a single entry (crediting every
matching ticker instead of showing duplicates), drops articles older than a
week once there's enough fresh material to fill the feed, and down-ranks
publishers found to be essentially unreadable past the headline (aggressive
paywalls, or broken article links) — see
`scripts/news_scrape_coverage.py` for the scrape-coverage check behind that
list. Alongside that, a watchlist card with live prices, day-change badges,
and sparklines — add a ticker with the input at the bottom (it's validated
against a real quote before it's added — a typo gets rejected inline) and
remove one by hovering a row and clicking the ×. Below that, market-mover
panels — Trending, Most Active, Top Gainers, Top Losers — each linking
through to a full paginated screen.

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

**Brokerage (`/brokerage`)** — connect a real brokerage account (via
SnapTrade's OAuth-style link flow) and see live positions, orders, and news
for what you actually hold. Read-only: positions/balances are fetched live
on every load and never persisted, only which brokerage/account you've
connected is. A few things worth knowing:
- **Multiple accounts** — each connected brokerage shows as a card (name,
  logo, connection status, a × to disconnect); an account picker switches
  the Positions/Orders/News tabs between "All accounts" (combined) and any
  one account individually.
- **Positions tab** — table or heatmap (treemap sized by market value,
  colored by today's % change) view, plus an After Hours toggle that swaps
  in extended-hours price/change once the market's closed.
- **Orders tab** — recent account activity (trades, dividends, transfers)
  with a signed amount column.
- **News tab** — pulls headlines scoped to whichever positions are in view
  (deduped, capped at 40 symbols so the query stays bounded for large
  portfolios) through the same ranked/deduped news pipeline the Dashboard
  uses.
- **Daily Digest tab** — an AI-written article on how your portfolio
  performed today and why, plus what to watch next. Generated on demand
  (never automatically) since it's a real Bedrock call; claims in the
  article and its key drivers/watch items are inline-cited back to the news
  they're grounded in, with a Sources list at the bottom linking to the
  original articles.
- Prices auto-refresh every 30s while the tab is visible, with a "last
  updated" timestamp next to the total.

**Markets (`/markets/...`)** — paginated screens for stocks (most-active,
gainers, losers, top-performing, trending, best-historical, top ETFs),
options (most-active, highest open interest), and private companies
(highest-valuation), reachable from the Dashboard's mover panels or the nav
bar.

## Tests

```bash
make test            # both, or run individually:
uv run pytest         # backend
cd webapp && npm test # frontend (Vitest)
```

## Project layout

```
src/
  agents/     # CLI entrypoint, chat agent, multi-agent stock team
  core/       # shared agent config, tools, FastAPI app, SSE helpers
webapp/       # React + Vite frontend
tests/        # pytest suite
scripts/      # one-off diagnostics, e.g. news_scrape_coverage.py
```
