"""Deterministic guard against a specialist citing a number its own tools
never returned this run - catches a hallucinated RSI/volatility/P-E figure
before it reaches the synthesizer, without spending another LLM call to
check it.

Registered as an `output_validator` on each tool-using specialist in
stock_team.py. Only checks numbers with a decimal point (bare integers like
"20-day"/"52-week" are period labels, not tool-cited figures, and flagging
them would just burn the agent's one retry on false positives).
"""

import re

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ToolReturnPart

from core.models import SpecialistFinding

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.\d+")
_RELATIVE_TOLERANCE = 0.02
# Analysts abbreviate ("$2.8T market cap") and yfinance mixes fractions with
# percents (a 0.65 margin cited as "65%") - scale a tool-returned number by
# each of these before giving up on a match, instead of only comparing it
# literally.
_SCALE_FACTORS = (1, 100, 1 / 100, 1e3, 1e-3, 1e6, 1e-6, 1e9, 1e-9, 1e12, 1e-12)


def _iter_numbers(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        numbers = []
        for v in value.values():
            numbers.extend(_iter_numbers(v))
        return numbers
    if isinstance(value, (list, tuple)):
        numbers = []
        for v in value:
            numbers.extend(_iter_numbers(v))
        return numbers
    return []


def _tool_result_numbers(messages) -> list[float]:
    numbers = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart):
                numbers.extend(_iter_numbers(part.content))
    return numbers


def _cited_numbers(finding: SpecialistFinding) -> list[float]:
    text = finding.headline + " " + " ".join(finding.key_points)
    return [float(match.replace(",", "")) for match in _NUMBER_RE.findall(text)]


def _matches_any(value: float, pool: list[float]) -> bool:
    if value == 0:
        return any(candidate == 0 for candidate in pool)
    for candidate in pool:
        if candidate == 0:
            continue
        for scale in _SCALE_FACTORS:
            scaled = candidate * scale
            if abs(value - scaled) <= abs(scaled) * _RELATIVE_TOLERANCE:
                return True
    return False


# Pairwise combos to try when a cited number isn't literally in the pool -
# specialists routinely report a *derived* stat ("19.5% below its 52-week
# high") that's arithmetically correct but isn't itself one of the raw
# numbers a tool returned. Capped to a deduped, size-limited pool since this
# is O(n^2) and some tools return long series (e.g. get_similar_tickers'
# per-peer day_prices).
_PAIRWISE_POOL_CAP = 120


def _matches_derived(value: float, pool: list[float]) -> bool:
    unique = sorted(set(pool))
    if len(unique) > _PAIRWISE_POOL_CAP:
        return False
    for a in unique:
        for b in unique:
            if a is b:
                continue
            for derived in (abs(a - b), (a - b) / b * 100 if b else None, (b - a) / a * 100 if a else None):
                if derived is None:
                    continue
                tolerance = max(abs(derived), 1) * _RELATIVE_TOLERANCE
                if abs(value - derived) <= tolerance:
                    return True
    return False


def check_findings_are_grounded(ctx: RunContext, finding: SpecialistFinding) -> SpecialistFinding:
    """output_validator: flags a finding whose headline/key_points cite
    numbers that mostly don't trace back to any figure (or derived
    difference/percent-change between two figures) this run's own tools
    actually returned.

    Deliberately requires a *majority* of cited numbers to be unmatched
    (not just one) before raising `ModelRetry` - the agent only gets one
    retry (see config.yaml's `retries`), so a single false positive on a
    legitimately-derived stat would otherwise hard-fail the whole run.
    """
    pool = _tool_result_numbers(ctx.messages)
    if not pool:
        return finding
    cited = _cited_numbers(finding)
    if not cited:
        return finding
    unmatched = [n for n in cited if not _matches_any(n, pool) and not _matches_derived(n, pool)]
    if len(unmatched) > len(cited) / 2:
        raise ModelRetry(
            f"Most of the figures in your headline/key_points don't match any number (or derived "
            f"difference/percent-change between two numbers) your tools actually returned this run: "
            f"{unmatched}. Cite exact figures from the tool results only, don't estimate or round to a "
            "different value."
        )
    return finding
