"""Writes llm_call_log rows - real per-call cost via genai_prices (already a
pydantic-ai dependency), not an estimate. Parallel to core/audit.py, but a
separate table since AuditLogEntry is deliberately not a generic event bus
and its `detail` column isn't structured enough for token/cost fields.
"""

import genai_prices
import yaml
from pydantic_ai.usage import RunUsage
from sqlalchemy.orm import Session as DbSession

from core.config import CONFIG_PATH
from core.models_db import LlmCallLog

_MODEL_REF = yaml.safe_load(CONFIG_PATH.read_text())["model"]["name"]


def log_llm_usage(db: DbSession, user_id: int | None, call_site: str, usage: RunUsage) -> None:
    price = genai_prices.calc_price(usage, _MODEL_REF, provider_id="bedrock")
    db.add(
        LlmCallLog(
            user_id=user_id,
            call_site=call_site,
            model=_MODEL_REF,
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=float(price.total_price),
        )
    )
    db.commit()
