"""Builds a pydantic-ai Agent from config.yaml so scripts don't repeat provider boilerplate."""

from pathlib import Path
from typing import Any, Sequence

import yaml
from pydantic_ai import Agent
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider

import core.env  # noqa: F401 - loads .env, so AWS_* creds can come from it too

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_agent(
    tools: Sequence[callable] = (), deps_type: type = object, output_type: Any = str, retries: int | None = None
) -> Agent:
    """Build an Agent from config.yaml.

    Args:
        tools: plain functions (e.g. from tools.py) to register on the agent.
        deps_type: type of the object passed as `deps=` at run time; tools
            can declare a `ctx: RunContext[deps_type]` first parameter to
            read it. Defaults to `object` for agents that don't use deps.
        output_type: structured output type, if fixed for every run of this
            agent. Must be set here (not passed to `.run(output_type=...)`)
            for any agent that also registers an `output_validator`, since
            pydantic-ai forbids overriding output_type per-run once
            output_validators are attached. Defaults to `str`.
        retries: overrides config.yaml's `agent.retries` for this agent only
            - e.g. a higher budget for an agent with an `output_validator`,
            so one borderline validation failure doesn't exhaust the retry
            budget and hard-fail the run.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text())

    provider = BedrockProvider(**config["provider"])
    model = BedrockConverseModel(config["model"]["name"], provider=provider)

    return Agent(
        model,
        model_settings=config.get("model_settings") or None,
        system_prompt=config["agent"].get("system_prompt") or (),
        retries=retries if retries is not None else config["agent"].get("retries", 1),
        tools=tools,
        deps_type=deps_type,
        output_type=output_type,
    )
