"""Resilient parallel agent.

Runs sub-agents concurrently like ADK ParallelAgent, but isolates failures
per sub-agent so one transient transport error does not fail the whole batch.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from google.adk.agents import ParallelAgent
from google.adk.agents.base_agent import BaseAgentState
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.utils.context_utils import Aclosing
from typing_extensions import override

logger = logging.getLogger(__name__)


def _create_branch_ctx_for_sub_agent(
    agent: ParallelAgent,
    sub_agent,
    invocation_context: InvocationContext,
) -> InvocationContext:
    """Create an isolated branch context for each sub-agent."""
    branch_ctx = invocation_context.model_copy()
    branch_suffix = f"{agent.name}.{sub_agent.name}"
    branch_ctx.branch = (
        f"{branch_ctx.branch}.{branch_suffix}" if branch_ctx.branch else branch_suffix
    )
    return branch_ctx


async def _merge_agent_run_resilient(
    agent_runs: list[AsyncGenerator[Event, None]],
    sub_agent_names: list[str],
) -> AsyncGenerator[Event, None]:
    """Merge async event streams while isolating per-agent exceptions."""
    sentinel = object()
    queue: asyncio.Queue = asyncio.Queue()

    async def process_an_agent(idx: int, events_for_one_agent):
        try:
            async for event in events_for_one_agent:
                resume_signal = asyncio.Event()
                await queue.put((event, resume_signal))
                await resume_signal.wait()
        except Exception:
            logger.exception(
                "Sub-agent '%s' failed during resilient parallel execution.",
                sub_agent_names[idx],
            )
        finally:
            await queue.put((sentinel, None))

    async with asyncio.TaskGroup() as tg:
        for idx, events_for_one_agent in enumerate(agent_runs):
            tg.create_task(process_an_agent(idx, events_for_one_agent))

        sentinel_count = 0
        while sentinel_count < len(agent_runs):
            event, resume_signal = await queue.get()
            if event is sentinel:
                sentinel_count += 1
            else:
                yield event
                resume_signal.set()


class ResilientParallelAgent(ParallelAgent):
    """Parallel agent that continues when individual sub-agents fail."""

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        if not self.sub_agents:
            return

        agent_state = self._load_agent_state(ctx, BaseAgentState)
        if ctx.is_resumable and agent_state is None:
            ctx.set_agent_state(self.name, agent_state=BaseAgentState())
            yield self._create_agent_state_event(ctx)

        agent_runs: list[AsyncGenerator[Event, None]] = []
        sub_agent_names: list[str] = []
        for sub_agent in self.sub_agents:
            sub_agent_ctx = _create_branch_ctx_for_sub_agent(self, sub_agent, ctx)
            if not sub_agent_ctx.end_of_agents.get(sub_agent.name):
                agent_runs.append(sub_agent.run_async(sub_agent_ctx))
                sub_agent_names.append(sub_agent.name)

        pause_invocation = False
        try:
            async with Aclosing(
                _merge_agent_run_resilient(agent_runs, sub_agent_names)
            ) as agen:
                async for event in agen:
                    yield event
                    if ctx.should_pause_invocation(event):
                        pause_invocation = True

            if pause_invocation:
                return

            if ctx.is_resumable:
                ctx.set_agent_state(self.name, end_of_agent=True)
                yield self._create_agent_state_event(ctx)
        finally:
            for sub_agent_run in agent_runs:
                try:
                    await sub_agent_run.aclose()
                except Exception:
                    logger.debug("Ignoring sub-agent close error.", exc_info=True)
