"""Diagnostic CLI for the Stock Team (src/agents/stock_team.py): runs each
specialist individually (or the full synthesizer) against a real ticker and
prints every tool call/result plus the final structured output, so you can
see exactly what each agent looked up and concluded without going through
the API/webapp.

Run with:
    uv run python scripts/run_team_analysis.py NVDA                 # full team
    uv run python scripts/run_team_analysis.py NVDA --agent risk     # one specialist
    uv run python scripts/run_team_analysis.py NVDA --agent all      # every specialist, one at a time, no synthesizer
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, AsyncIterable

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pydantic_ai.messages import (  # noqa: E402
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.tools import RunContext  # noqa: E402

from agents.stock_team import (  # noqa: E402
    TeamDeps,
    fundamentals_agent,
    get_team_analysis,
    portfolio_fit_agent,
    risk_agent,
    sentiment_agent,
    synthesizer,
    technicals_agent,
    valuation_agent,
)
from core.models import SpecialistFinding  # noqa: E402

# Claude Sonnet 5 (config.yaml's model) list pricing per 1M tokens - Bedrock
# bills Anthropic models at these same rates. Update if config.yaml's model
# changes.
_INPUT_USD_PER_MILLION = 2.00
_OUTPUT_USD_PER_MILLION = 10.00


def _cost_usd(usage) -> float:
    return (
        usage.input_tokens / 1_000_000 * _INPUT_USD_PER_MILLION
        + usage.output_tokens / 1_000_000 * _OUTPUT_USD_PER_MILLION
    )

# Mirrors each delegator tool's prompt in stock_team.py, so running a
# specialist standalone asks it exactly what the synthesizer would.
SPECIALISTS = {
    "fundamentals": (
        fundamentals_agent,
        "Look up {ticker}'s current price, market cap, and P/E ratio, then judge whether that profile "
        "looks positive, neutral, or negative for the stock.",
    ),
    "sentiment": (
        sentiment_agent,
        "Based on recent headlines, judge whether sentiment on {ticker} is positive, neutral, or negative.",
    ),
    "technicals": (
        technicals_agent,
        "Look up {ticker}'s computed technical indicators (20/50/200-day moving averages, RSI-14, MACD) "
        "and trailing price performance/52-week range, then judge whether current momentum/trend is "
        "positive, neutral, or negative. Cite the actual indicator values and crossovers.",
    ),
    "valuation": (
        valuation_agent,
        "Look up {ticker}'s valuation (P/E, EV/EBITDA, price-to-sales, etc.) and its industry/sector "
        "peers, then judge whether it looks cheap (positive), fairly valued (neutral), or expensive "
        "(negative) relative to those peers.",
    ),
    "risk": (
        risk_agent,
        "Look up {ticker}'s beta, computed 30-day annualized realized volatility, and trailing price "
        "performance, then judge its volatility/downside risk as low (positive), moderate (neutral), or "
        "high (negative). Cite the actual computed volatility figure, not just beta.",
    ),
    "portfolio_fit": (
        portfolio_fit_agent,
        "Given this portfolio, judge how holding/adding {ticker} affects concentration and "
        "diversification: positive, neutral, or negative. (No real portfolio_summary supplied here - "
        "this is a standalone smoke test of the agent/tools, not the real delegator prompt.)",
    ),
}


def _fmt_scalar(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.4g}"
    return str(value)


def _fmt_value(value: Any, indent: int = 4) -> str:
    """Renders a tool call's args or a tool result as indented `key: value`
    lines (dicts) or a bulleted list (lists) instead of one long repr, so
    wide payloads (10+ numeric fields, headline lists) stay scannable.
    """
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return f"{pad}(empty)"
        width = max(len(str(k)) for k in value)
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(_fmt_value(v, indent + 4))
            else:
                lines.append(f"{pad}{str(k):<{width}} = {_fmt_scalar(v)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{pad}(empty)"
        return "\n".join(f"{pad}- {_fmt_scalar(item)}" for item in value)
    return f"{pad}{_fmt_scalar(value)}"


def make_event_printer(label: str = ""):
    """Builds an event_stream_handler that prints every tool call/result
    (pretty-printed) and streams text deltas live. `label` prefixes each
    line so nested specialist calls are distinguishable from the
    synthesizer's own tool calls when running the full team.
    """
    prefix = f"[{label}] " if label else ""

    async def print_events(ctx: RunContext, events: AsyncIterable[AgentStreamEvent]) -> None:
        async for event in events:
            match event:
                case FunctionToolCallEvent():
                    print(f"\n{prefix}→ CALL  {event.part.tool_name}", flush=True)
                    print(_fmt_value(event.part.args), flush=True)
                case FunctionToolResultEvent():
                    print(f"{prefix}← RESULT {event.part.tool_name}", flush=True)
                    print(_fmt_value(event.part.content), flush=True)
                case PartStartEvent(part=TextPart(content=text)):
                    print(text, end="", flush=True)
                case PartDeltaEvent(delta=TextPartDelta(content_delta=text)):
                    print(text, end="", flush=True)

    return print_events


def print_finding(name: str, finding: SpecialistFinding) -> None:
    print(f"\n{'-' * 70}")
    print(f"{name.upper()} → {finding.signal.upper()}")
    print(f"{'-' * 70}")
    print(finding.headline)
    for point in finding.key_points:
        print(f"  - {point}")


async def run_specialist(name: str, ticker: str) -> None:
    agent, prompt_template = SPECIALISTS[name]
    print(f"\n{'=' * 70}\n{name.upper()} SPECIALIST on {ticker}\n{'=' * 70}")
    # portfolio_fit_agent has no output_validator, so unlike the other five
    # specialists its output_type isn't fixed at construction in
    # stock_team.py and must be passed here instead.
    output_type_kwargs = {"output_type": SpecialistFinding} if name == "portfolio_fit" else {}
    result = await agent.run(
        prompt_template.format(ticker=ticker),
        event_stream_handler=make_event_printer(),
        **output_type_kwargs,
    )
    print_finding(name, result.output)
    print(f"\ntokens: {result.usage}")
    print(f"cost:   ${_cost_usd(result.usage):.4f}")


async def run_full_team(ticker: str) -> None:
    print(f"\n{'=' * 70}\nSYNTHESIZER (full team) on {ticker}\n{'=' * 70}")
    print("(No db/user_id passed, so portfolio_fit will short-circuit to its no-brokerage default.)")

    result = await get_team_analysis(ticker, event_stream_handler=make_event_printer("synthesizer"))
    verdict = result.verdict

    print(f"\n\n{'=' * 70}")
    print(f"FINAL VERDICT: {verdict.verdict.upper()}  ({ticker})")
    print(f"{'=' * 70}")
    print(f"Held: {result.is_held}")
    print(f"tokens: {result.usage}")
    print(f"cost:   ${_cost_usd(result.usage):.4f}  (all 6 specialists + synthesizer, rolled up)")
    print(f"Target: {verdict.predicted_price:,.2f} over {verdict.predicted_horizon}")
    print("\nKey factors:")
    for factor in verdict.key_factors:
        print(f"  - {factor}")
    print(f"\nReasoning: {verdict.reasoning}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ticker", help="Stock ticker symbol, e.g. NVDA")
    parser.add_argument(
        "--agent",
        choices=[*SPECIALISTS, "all", "team"],
        default="team",
        help="Which agent to run: a single specialist name, 'all' (every specialist, no synthesizer), "
        "or 'team' (full synthesizer run, default).",
    )
    args = parser.parse_args()
    ticker = args.ticker.upper()

    if args.agent == "team":
        await run_full_team(ticker)
    elif args.agent == "all":
        for name in SPECIALISTS:
            await run_specialist(name, ticker)
    else:
        await run_specialist(args.agent, ticker)


if __name__ == "__main__":
    asyncio.run(main())
