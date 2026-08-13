"""Builds a pydantic-ai Agent from config.yaml so scripts don't repeat provider boilerplate."""

from pathlib import Path
from typing import Sequence

import yaml
from pydantic_ai import Agent
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider

import core.env  # noqa: F401 - loads .env, so AWS_* creds can come from it too

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_agent(tools: Sequence[callable] = (), deps_type: type = object) -> Agent:
    """Build an Agent from config.yaml.

    Args:
        tools: plain functions (e.g. from tools.py) to register on the agent.
        deps_type: type of the object passed as `deps=` at run time; tools
            can declare a `ctx: RunContext[deps_type]` first parameter to
            read it. Defaults to `object` for agents that don't use deps.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text())

    provider = BedrockProvider(**config["provider"])
    model = BedrockConverseModel(config["model"]["name"], provider=provider)

    return Agent(
        model,
        model_settings=config.get("model_settings") or None,
        system_prompt=config["agent"].get("system_prompt") or (),
        retries=config["agent"].get("retries", 1),
        tools=tools,
        deps_type=deps_type,
    )
