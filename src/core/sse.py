"""SSE plumbing shared by the streaming routes.

`agent.run()` + `event_stream_handler=` (Lesson 13) delivers tool-call/tool-
result/text-delta events to a callback *while* the run is in progress, but
the callback has no way to hand them back out to an async generator on its
own - `run_agent_streaming` bridges that gap with a queue: the handler
pushes every event it receives, a background task drives the run to
completion and pushes the caller's return value wrapped in `Final`, and
this generator drains the queue in event-arrival order for a route to
format as SSE.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import AgentStreamEvent
from pydantic_ai.tools import RunContext

_DONE = object()


@dataclass
class Final:
    """Wraps whatever `run` returned, so it's unambiguous even if that
    value happens to itself be a stream event or an Exception instance.
    """

    value: Any


def format_sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def run_agent_streaming(
    run: Callable[[Callable], Awaitable[Any]],
) -> AsyncIterator[AgentStreamEvent | Final]:
    """Drive one `agent.run(..., event_stream_handler=...)` call (or a
    function that wraps one, like `chat.send_message`/
    `stock_team.get_team_analysis`), yielding every stream event followed
    by a `Final` wrapping `run`'s return value.

    `run` is a callable that takes an `event_stream_handler` and awaits the
    agent call with it attached - the caller supplies everything
    route-specific (which agent, what prompt, deps) while this function
    only owns the queue/generator bridging.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def handler(ctx: RunContext, events: AsyncIterator[AgentStreamEvent]) -> None:
        async for event in events:
            await queue.put(event)

    async def drive() -> None:
        try:
            result = await run(handler)
        except Exception as e:  # noqa: BLE001 - re-raised on the consumer side below
            await queue.put(e)
        else:
            await queue.put(Final(result))
        finally:
            await queue.put(_DONE)

    task = asyncio.create_task(drive())
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        await task
