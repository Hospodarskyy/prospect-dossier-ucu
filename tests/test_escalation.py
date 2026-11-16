"""Offline tests for EscalationChecker: stop the loop only on status == 'pass'."""
import asyncio
from types import SimpleNamespace

import pytest

from dossier_agent.agent import EscalationChecker


def test_counts_iterations():
    ctx = SimpleNamespace(invocation_id="inv-1", session=SimpleNamespace(state={"iterations": 2}))

    async def collect():
        return [e async for e in EscalationChecker()._run_async_impl(ctx)]

    assert asyncio.run(collect())[0].actions.state_delta == {"iterations": 3}


def _events(feedback):
    ctx = SimpleNamespace(invocation_id="inv-1", session=SimpleNamespace(state={"judge_feedback": feedback}))

    async def collect():
        return [e async for e in EscalationChecker()._run_async_impl(ctx)]

    return asyncio.run(collect())


@pytest.mark.parametrize("feedback", [{"status": "pass"}, '{"status": "pass"}'])
def test_escalates_on_pass(feedback):
    events = _events(feedback)
    assert len(events) == 1 and events[0].actions.escalate is True


@pytest.mark.parametrize("feedback", [
    {"status": "fail"}, {"verdict": "pass"}, "not json", None, {},
])
def test_no_escalation_otherwise(feedback):
    events = _events(feedback)
    assert len(events) == 1 and not events[0].actions.escalate


def test_custom_agent_events_belong_to_the_invocation():
    """Events of the agents without LLM carry the invocation id: ADK groups a
    run's events by it (adk eval found 2 invocations per run without it)."""
    events = _events({"status": "pass"})
    assert events[0].invocation_id == "inv-1"
