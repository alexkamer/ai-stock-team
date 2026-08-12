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

The Vite dev server proxies `/api` to the backend, so run both together while developing.

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
