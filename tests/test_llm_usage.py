"""Tests for core/llm_usage.py - logging real per-call LLM cost via
genai_prices. Uses the same isolated-DB approach as test_auth.py."""

from pydantic_ai.usage import RunUsage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.llm_usage import log_llm_usage
from core.models_db import LlmCallLog


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_log_llm_usage_writes_row_with_real_cost():
    db = _make_session()
    usage = RunUsage(requests=1, input_tokens=1000, output_tokens=500)

    log_llm_usage(db, 7, "digest", usage)

    rows = db.query(LlmCallLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == 7
    assert row.call_site == "digest"
    assert row.input_tokens == 1000
    assert row.output_tokens == 500
    assert row.cost_usd > 0
    db.close()


def test_log_llm_usage_allows_null_user_id():
    db = _make_session()
    usage = RunUsage(requests=1, input_tokens=100, output_tokens=50)

    log_llm_usage(db, None, "team_analysis", usage)

    row = db.query(LlmCallLog).one()
    assert row.user_id is None
    db.close()
