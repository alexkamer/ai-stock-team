# Webapp Roadmap

Turning the `lessons/` pydantic-ai concepts into an actual web app: a
FastAPI backend wrapping the existing agents, a React/Vite frontend on
top. Distinct from `lessons/ROADMAP.md`, which tracks the learning
curriculum this app is built out of.

## Layout

App code lives under `src/` as two top-level packages, both
editable-installed via `pyproject.toml`/hatchling: `agents/` (`main.py`
CLI, `chat.py`, `stock_team.py`) and `core/` (`api.py` FastAPI app,
`sse.py` streaming plumbing, `tools.py`, `models.py`, `config.py` +
`config.yaml`). `api.py`/`sse.py` live inside `core/` rather than directly
under `src/` so hatchling's editable install symlinks them like every
other module instead of copying them statically (a bare `src/api.py`
would get force-included as a stale snapshot that silently stops tracking
edits). `tests/` imports the real packages (`from core import api,
tools`, `from agents import chat`, etc.) - no `sys.path` hacks.
Root-level `config.py`/`tools.py`/`main.py` are thin re-export shims kept
only so `lessons/` scripts (which `sys.path.insert` to the repo root, not
`src/`, and are intentionally left standalone per the curriculum) keep
running unmodified.

## Stack

- **Backend:** FastAPI. Wraps `main.py`'s agent + the Lesson 09 multi-agent
  team as HTTP endpoints. Streaming pages use Server-Sent Events (or a
  streaming HTTP response) so the frontend can render tokens/tool-call
  status incrementally, the same way `run_stream()` (Lesson 07) does in a
  terminal.
- **Frontend:** Vite + React. One route per page below, a shared
  fetch/SSE client for streaming responses, and a shared "tool call in
  flight" indicator component (three of four pages need it).

## Pages

### 1. Dashboard (landing page)

**Purpose:** at-a-glance view of the user's watchlist; also the hub linking
to the other pages.

**Layout (top to bottom):**

- **Header bar** - app name/logo + a ticker search/jump box. Free-types any
  symbol (not just watchlist tickers) and routes straight to Ticker Detail
  on submit; client-side validation only, no backend call until the detail
  page loads.
- **Market snapshot strip** - small row of index quotes (S&P 500, Nasdaq,
  Dow) for ambient context. No new tool logic needed - reuse
  `get_stock_price`/`get_price_history` against index tickers (`^GSPC`,
  `^IXIC`, `^DJI`).
- **Watchlist grid** - one card per ticker from a hardcoded default list
  (e.g. NVDA, AAPL, MSFT, GOOGL, AMZN): ticker + company name, current
  price, day change (color-coded), small sparkline. Click opens Ticker
  Detail. A trailing "+ Add ticker" tile is visible but disabled/tooltipped
  - real add/remove is Phase 4.
  - Needs a batch endpoint (e.g. `GET /watchlist` or
    `/tickers?symbols=...`) returning price + change + sparkline data for
    all tickers in one call, not one round trip per card. Decide the exact
    shape in Phase 0. The market strip can reuse the same endpoint against
    index symbols.
- **Quick nav cards** - below the grid, cards linking to Stock Team
  Analysis and Research Chat, each with a one-line description.

**Powered by:** `Watchlist` deps + `get_watchlist_prices` (Lesson 04).
Sparkline needs `get_price_history` per ticker, batched behind the one
endpoint above rather than called per-card client-side.

**Out of scope for v1:** no add/remove UI wired to a backend, no
auth/user concept.

### 2. Ticker Detail

**Purpose:** deep-dive on one company - the same "snapshot" `main.py`
already produces, in a UI.

**Layout:** header (name, ticker, price, day change) -> stat row (market
cap, P/E) -> sentiment badge (bullish/bearish/neutral) -> AI summary
paragraph -> news headlines list -> price history chart with a period
selector (1d/1mo/6mo/1y).

**Powered by:** `CompanySnapshot` agent (Lessons 01-03), `get_price_history`.
Summary text streams in (Lesson 07) instead of appearing behind a spinner.

### 3. Stock Team Analysis

**Purpose:** the "should I buy this" page - the Lesson 09 multi-agent
synthesis, made visible instead of hidden inside one final answer.

**Layout:** Fundamentals card (from `fundamentals_agent`) and Sentiment
card (from `sentiment_agent`) populate first; a Synthesizer verdict panel
(Buy/Hold/Sell badge + reasoning) streams in below once both specialists
finish. Showing the specialists' work before the verdict keeps the
reasoning legible instead of a black box.

**Powered by:** `fundamentals_agent` + `sentiment_agent` + `synthesizer`
(Lesson 09), streamed (Lesson 07).

### 4. Research Chat

**Purpose:** open-ended conversational assistant for questions that don't
fit a fixed template - "what about its competitors?", "is that P/E high
for tech?".

**Layout:** standard chat UI - message history, streaming assistant
replies token-by-token, small inline pills showing tool calls in flight
("checking price...", "checking news...").

**Powered by:** `message_history` (Lesson 05) for multi-turn context,
dynamic system prompt injecting today's date + the user's watchlist
(Lesson 08) so "how's my portfolio doing" resolves without the user typing
tickers, streaming (Lesson 07).

### 5. Watchlist Settings *(deferred - see Phase 4)*

**Purpose:** add/remove the tickers that feed the Dashboard and the Chat's
system-prompt context.

**Layout:** list with a remove button per ticker + a text input to add
one, validated against a real lookup before adding so typos fail fast.

**Powered by:** `Watchlist` dataclass (Lesson 04) - this page is CRUD over
that. A hardcoded default watchlist is enough until this phase.

## Phases

### Phase 0 - API contract & state design (done)

- **Routes:** `/tickers/{ticker}` (snapshot), `/tickers/{ticker}/team`
  (multi-agent analysis), `/chat` (conversational), `/watchlist` (batch quote
  read for the Dashboard now; CRUD added in Phase 4).

- **`GET /watchlist` response shape:**

  ```json
  [
    {
      "ticker": "NVDA",
      "company_name": "NVIDIA Corporation",
      "price": 132.45,
      "day_change_percent": 1.8,
      "day_change_abs": 2.34,
      "sparkline": [128.1, 129.4, "..."]
    }
  ]
  ```

  `price`/`day_change_*` come from the same `yf.Ticker(...).info` payload
  `_get_info` already caches (`regularMarketChangePercent`/
  `regularMarketChange`) - no new tool needed. `sparkline` needs a new
  sibling tool, `get_sparkline_prices(ticker, period="1mo")`, returning raw
  closes - `get_price_history`'s summary-stat shape (start/end/high/low)
  stays as-is for agent reasoning rather than being bloated for UI needs.
  The endpoint loops over tickers server-side and returns one array, so the
  Dashboard fires a single request instead of one per card. The market
  snapshot strip reuses this same endpoint against index tickers
  (`^GSPC`, `^IXIC`, `^DJI`).

- **Streaming transport: SSE.** Maps directly onto `run_stream()`'s output -
  text deltas as `data: ...` events, plus a second event type
  (`event: tool_call`) for the "checking price..." pills on Stock Team/Chat.
  FastAPI's `StreamingResponse` supports this natively; frontend uses
  `fetch` + a small manual SSE parser (or `EventSource` for GET-only cases).

- **Chat history: server-side session by ID.** Backend keeps an in-memory
  `dict[session_id, list[ModelMessage]]` (the `all_messages()` output from
  Lesson 05), keyed by a UUID generated on the first message and echoed
  back by the client each turn. Chosen over client-resent history because
  the dynamic system prompt (today's date + watchlist, Lesson 08) has to be
  recomputed server-side every turn regardless, and this avoids shipping a
  growing message-history JSON blob on every request. In-memory is
  sufficient for v1 - no auth, restart clears sessions, matches the
  roadmap's existing scope.

### Phase 1 - Backend skeleton (in progress)

- `api.py` - FastAPI app wrapping `tools.py`/`stock_team.py`/`chat.py`,
  non-streaming JSON. Done so far:
  - `GET /watchlist` - batched quotes (price, day change, sparkline, company
    name) for the hardcoded `DEFAULT_WATCHLIST`, per Phase 0's response
    shape.
  - `GET /tickers/{ticker}` - full snapshot, streamed as SSE like the team
    endpoint below: `tool_call`/`tool_result`/`text` events while the
    `CompanySnapshot` agent (Lessons 01-03, `agents/main.py`'s new
    `get_snapshot_streaming`) reasons about sentiment/summary, then a
    terminal `snapshot` event merging that agent output with the plain
    tool data (day change, news headlines) computed up front. An `error`
    event replaces the old 404 for unknown tickers, same pattern as the
    team route.
  - `GET /tickers/{ticker}/team` - Stock Team multi-agent verdict
    (fundamentals + sentiment specialists delegated to by a synthesizer,
    Lesson 09), streamed as SSE (see below). Delegation logic lives in
    `stock_team.py`, not `api.py` directly, so the agent wiring can be
    unit-tested independent of the HTTP layer.
  - `POST /chat` - conversational endpoint backed by `chat.py`: one agent
    with a dynamic system prompt (today's date + watchlist, Lesson 08) and
    server-side session state (in-memory `dict[session_id, messages]`,
    Lesson 05/Phase 0). Takes `{message, session_id?}`, streams a
    `session` event carrying a UUID (generated on first message) followed
    by the reply as SSE.
  - **SSE is live for both routes.** `stock_team.get_team_analysis` and
    `chat.send_message` both accept an optional `event_stream_handler`
    (threaded straight into `agent.run()`, Lesson 13); `sse.py`'s
    `run_agent_streaming` bridges that callback-style handler into an
    async generator via a queue (a background task drives the run to
    completion and pushes a `Final(value)` wrapper once it's done, so the
    consumer can tell "last real event" apart from "the function's actual
    return value" even when that value happens to collide with an event
    type). `api.py`'s `_sse_event_for` maps each pydantic-ai stream event
    to an SSE `event:`/`data:` pair - `tool_call`/`tool_result` for
    `FunctionToolCallEvent`/`FunctionToolResultEvent`, `text` for streamed
    text deltas, plus route-specific terminal events (`verdict` for the
    team endpoint, nothing extra for chat since the text deltas already
    carry the reply) and an `error` event if the run raises `ValueError`
    (unknown ticker) mid-stream - can't 404 with a status code once the
    response has already started streaming.
  - `GET /watchlist?symbols=A,B,C` - the `symbols` query param overrides
    the hardcoded default list, so the Dashboard's market snapshot strip
    can reuse this endpoint against index tickers (`^GSPC`, `^IXIC`,
    `^DJI`) with one extra request instead of a second route.
  - `GET /tickers/{ticker}/history?period=` - plain JSON (`{period,
    prices}`), backing Ticker Detail's price chart period selector;
    thin wrapper over `get_sparkline_prices`, 404s like the snapshot
    route used to.
  - New `tools.py` additions backing these: `get_company_name`,
    `get_day_change`, `get_sparkline_prices` - all with pytest coverage in
    `tests/test_tools.py`, mocked `yf.Ticker` like the existing tests.
  - New `models.py` addition: `TeamVerdict` (ticker/verdict/reasoning).
  - `tests/test_api.py` - `TestClient`-based tests per route; the two
    streaming routes use a small `parse_sse` helper to turn the response
    body back into `(event, data)` pairs for assertions. Same
    yfinance-mocking approach as before. `tests/test_stock_team.py` and
    `tests/test_chat.py` test the agent wiring directly via
    `agent.override(model=TestModel(...))` (Lesson 10), one override per
    agent (synthesizer + both specialists for stock_team, single agent for
    chat).
  - Added `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml`) so
    async agent-calling tests can use plain `async def test_...()`.
- Phase 1 backend work is now complete - remaining work moves to Phase 2
  (frontend).
- **Phase 2 addendum:** Phase 2 surfaced a gap Phase 1 missed - the
  Ticker Detail spec (sentiment badge + streamed AI summary) needs the
  `CompanySnapshot` agent from `agents/main.py` (Lessons 01-03), but that
  route had only ever wrapped raw tool data. Added
  `agents/main.py:get_snapshot_streaming` (async twin of the CLI's
  `get_snapshot`, threading `event_stream_handler` like `stock_team`/
  `chat` do) and converted `GET /tickers/{ticker}` from plain JSON to the
  same SSE pattern as `/tickers/{ticker}/team`, merging the streamed
  `CompanySnapshot` output with the day-change/news data already fetched
  up front into a terminal `snapshot` event. Also added
  `GET /tickers/{ticker}/history?period=` (plain JSON, wraps
  `get_sparkline_prices`) for the price chart's period selector, and gave
  `GET /watchlist` an optional `?symbols=` override so the Dashboard's
  market strip can reuse it for index tickers instead of a second route.

### Phase 2 - Frontend skeleton + Dashboard/Ticker Detail (done)

- `webapp/` - Vite + React (JS, not TS), `react-router-dom` for routing.
  Dev server proxies `/api/*` to the FastAPI backend on `:8000`
  (`vite.config.js`), so the frontend never hardcodes a backend origin.
- `src/api/client.js` - shared fetch client: `getJSON` for plain routes,
  `streamSSE` for the SSE routes (hand-rolled parser over a raw `fetch`
  body reader, not `EventSource` - `EventSource` can't send a POST body,
  which `/chat` needs).
- `src/components/ToolCallPill.jsx` + `useToolCalls.js` - the shared
  "tool call in flight" indicator: a pill per `tool_call` event, marked
  done on the matching `tool_result`. Used by Ticker Detail now; Stock
  Team/Chat reuse it in Phase 3.
- Dashboard (`src/pages/Dashboard.jsx`) - market snapshot strip (reuses
  `GET /watchlist?symbols=...` against index tickers per Phase 0/1),
  watchlist grid with sparklines, quick-nav cards. Disabled "+ Add
  ticker" tile per spec (Phase 4 wires it up).
- Ticker Detail (`src/pages/TickerDetail.jsx`) - required adding backend
  support that didn't exist yet (see Phase 1 addendum below): consumes
  the now-streaming `GET /tickers/{ticker}` for tool pills + AI
  sentiment/summary, and the new `GET /tickers/{ticker}/history` for the
  period-selectable price chart (`src/components/PriceChart.jsx`, with a
  hover crosshair per the dataviz interaction rule).
- Stock Team Analysis and Research Chat pages exist as Phase-3
  placeholders (`src/pages/StockTeam.jsx`, `ResearchChat.jsx`) so
  Dashboard's quick-nav links resolve instead of 404ing.
- Verified end-to-end in a real browser (Playwright) against the live
  backend (real yfinance + Bedrock calls, not mocks) - Dashboard renders
  live quotes/sparklines, Ticker Detail streams tool pills then the
  sentiment badge/summary/chart/news.

### Phase 2 addendum - Ticker Detail latency fix + visual system (done)

- **Latency fix.** Ticker Detail felt slow because `GET /tickers/{ticker}`
  routed price/market-cap/P/E/news through `get_snapshot_streaming`'s
  4-tools-plus-final-answer agent run (5 Bedrock round trips) before
  anything rendered, even though those four values are plain cached
  yfinance reads with no need for an LLM. Split the route into two SSE
  events: an immediate `quote` event (ticker, company name, price, market
  cap, P/E, day change, headlines - all direct `tools.py` calls, no
  agent) followed by a `sentiment` event from a new, tool-less
  `sentiment_agent` (`agents/main.py`) that takes the already-fetched
  headlines in its prompt instead of re-deriving them via tool calls -
  one Bedrock round trip instead of five. `core/models.py` gained
  `SentimentSummary` (sentiment + summary only) alongside the existing
  `CompanySnapshot`; the old `get_snapshot_streaming` was deleted as
  dead code once nothing called it. Frontend (`TickerDetail.jsx`) now
  renders header/stats/chart/news off `quote` alone and layers the
  sentiment badge/summary in once `sentiment` arrives.
- **Visual system.** Replaced the placeholder blue-accent theme with a
  "modern structured" system per user direction: geometric sans
  (Space Grotesk display / Inter body) + a monospace utility face (IBM
  Plex Mono) for labels/data, a neutral ink palette, and one sharp
  violet signal color (`--signal`, was `--accent`) instead of blue.
  Token system lives in `index.css` (`--paper`/`--surface-1/2`, `--good`/
  `--critical` with `-bg` tints, `--signal` with `-bg`/`-border`).
- **Dashboard rebuilt toward a Yahoo Finance-style homepage** (user
  request): the market strip now shows 8 instruments matching Yahoo's
  own homepage strip - S&P 500, Dow 30, Nasdaq, Russell 2000, VIX, Gold
  (`GC=F`), Bitcoin USD (`BTC-USD`), Crude Oil (`CL=F`) - up from the
  original 3 indices. All 8 resolve through the existing
  `GET /watchlist?symbols=...` endpoint with no backend changes; futures/
  crypto tickers work through `get_company_name`/`get_stock_price`/
  `get_day_change` same as equities. The strip scrolls horizontally with
  left/right nav buttons (disabled at each end, `scrollBy` on click) since
  8 instruments don't fit one viewport width. Watchlist changed from a
  card grid to a dense quote table (ticker/name, price, change badge,
  1M sparkline columns) - closer to a real quote board. A combined
  cross-watchlist news module (Yahoo's trending-news block) was
  considered and explicitly deferred, not forgotten.
- Verified in a real headless-Chromium session via Playwright against
  both live dev servers - Dashboard, Ticker Detail, and the Phase-3
  placeholder routes all render without console errors.

### Phase 3 - Stock Team Analysis + Research Chat (not yet started)

- Stock Team page: render the two specialist cards + streamed synthesizer
  verdict.
- Research Chat page: streaming chat UI, message history threading,
  tool-call-in-flight indicators.

### Phase 4 - Watchlist Settings (not yet started)

- CRUD UI + backend endpoint for the watchlist, replacing the hardcoded
  default used by Phases 1-3.
- Wire it into Dashboard (drives the grid) and Chat (drives the dynamic
  system prompt's portfolio context).

### Phase 5 - Polish (not yet started)

- Loading/error states for tool failures (e.g. bad ticker -> `ValueError`
  from `tools.py` should surface as a real UI error, not a stack trace).
- Revisit visual design once all pages exist end-to-end.

## Notes

- No new agent/tool logic is expected for v1 - every page maps to
  something already built and tested in `lessons/`, `tools.py`, and
  `main.py`. This roadmap is about exposing that work over HTTP + UI, not
  extending it.
- Update phase status (not yet started / in progress / done) as work
  lands, same convention as `lessons/ROADMAP.md`.
