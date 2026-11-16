"""Offline tests for hard stops, research stops and usage (item 9)."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google.genai import types

from dossier_agent import agent as agent_module
from dossier_agent.agent import (
    EscalationChecker, check_dossier_format, finalize_run, limit_after_model,
    limit_before_model,
)
from dossier_agent.limits import (
    Limits, add_response, elapsed_seconds, hard_stop_reason, new_usage, reported_searches,
    research_stop_reason,
)
from dossier_agent.pricing import FALLBACK_PRICE, price_for, token_cost, use_vertex
from dossier_agent.schemas import JudgeFeedback

LIMITS = Limits()   # spec defaults: 50 calls, $0.40, 540 s, 15 searches, 70% soft


# --------------------------------------------------------------------------
# pricing and usage accounting
# --------------------------------------------------------------------------
def test_token_cost_vertex_flash():
    # 10k input, 2k output, 3k thinking at $1.50 / $9.00 per 1M
    assert token_cost("gemini-3.5-flash", 10_000, 2_000, 3_000, vertex=True) == \
        pytest.approx(0.015 + 0.045)


def test_token_cost_gemini_api_flash():
    # 10k input, 2k output, 3k thinking at $0.75 / $3.75 per 1M
    assert token_cost("gemini-3.8-flash", 10_000, 2_000, 3_000, vertex=False) == \
        pytest.approx(0.0075 + 0.01875)


@pytest.mark.parametrize("vertex", [True, False])
def test_unknown_model_is_priced_as_the_most_expensive(vertex):
    assert price_for("gemini-99-ultra", vertex) == FALLBACK_PRICE[:2] == (1.50, 9.00)


def test_model_of_the_other_backend_is_not_cheap():
    # gemini-3.5-flash is not on the Gemini API price list: never under-count it
    assert price_for("gemini-3.5-flash", vertex=False) == FALLBACK_PRICE[:2]


@pytest.mark.parametrize("env,expected", [
    ({}, False),
    ({"GOOGLE_GENAI_USE_VERTEXAI": "TRUE"}, True),
    ({"GOOGLE_GENAI_USE_VERTEXAI": "1"}, True),
    ({"GOOGLE_GENAI_USE_VERTEXAI": "FALSE"}, False),
    ({"GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_GENAI_USE_ENTERPRISE": "false"}, False),
])
def test_backend_follows_google_genai_env(monkeypatch, env, expected):
    for name in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert use_vertex() is expected


def test_add_response_sums_tokens_and_cost():
    u = add_response(new_usage(), model="gemini-3.5-flash", input_tokens=1000, output_tokens=100,
                     thinking_tokens=200)
    u = add_response(u, model="gemini-3.5-flash", input_tokens=1000, output_tokens=100,
                     thinking_tokens=200)
    assert (u["input_tokens"], u["output_tokens"], u["thinking_tokens"]) == (2000, 200, 400)
    assert u["cost_usd"] == pytest.approx(2 * (1000 * 1.5 + 300 * 9.0) / 1e6)
    assert u["searches"] == 0 and u["searches_source"] == "none"


def test_add_response_does_not_change_the_input():
    usage = new_usage()
    add_response(usage, model=None, input_tokens=5, output_tokens=5, thinking_tokens=5)
    assert usage == new_usage()


def test_searches_from_grounding():
    u = add_response(new_usage(), model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     grounding_queries=["a", "b", "c"], is_researcher=True)
    u = add_response(u, model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     grounding_queries=["d"], is_researcher=True)
    assert (u["searches"], u["searches_source"]) == (4, "grounding")


def test_searches_fall_back_to_the_researchers_own_count():
    u = add_response(new_usage(), model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     response_text="Searches performed: 7 (queries: ...)", is_researcher=True)
    assert (u["searches"], u["searches_source"]) == (7, "model_reported")
    # the reported number is cumulative: a second report of 9 means 9 in total
    u = add_response(u, model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     response_text="Searches performed: 9", is_researcher=True)
    assert u["searches"] == 9


def test_searches_mixed_sources():
    u = add_response(new_usage(), model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     grounding_queries=["a", "b"], is_researcher=True)
    u = add_response(u, model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     response_text="Searches performed: 6", is_researcher=True)
    assert (u["searches"], u["searches_source"]) == (6, "mixed")


def test_judge_and_writer_responses_do_not_count_searches():
    u = add_response(new_usage(), model=None, input_tokens=0, output_tokens=0, thinking_tokens=0,
                     response_text="Searches performed: 7", is_researcher=False)
    assert u["searches"] == 0


@pytest.mark.parametrize("text,expected", [
    ("Searches performed: 5 (queries: x)", 5), ("searches performed:12", 12), ("no line", None), ("", None)])
def test_reported_searches(text, expected):
    assert reported_searches(text) == expected


# --------------------------------------------------------------------------
# limit checks
# --------------------------------------------------------------------------
def _usage(**over):
    return {**new_usage(), **over}


@pytest.mark.parametrize("usage,elapsed,expected", [
    (_usage(), 0, None),
    (_usage(llm_calls=49), 0, None),
    (_usage(llm_calls=50), 0, "llm_calls"),
    (_usage(cost_usd=0.3999), 0, None),
    (_usage(cost_usd=0.40), 0, "cost"),
    (_usage(), 539.9, None),
    (_usage(), 540, "time"),
])
def test_hard_stop_reason(usage, elapsed, expected):
    assert hard_stop_reason(usage, LIMITS, elapsed) == expected


@pytest.mark.parametrize("usage,expected", [
    (_usage(searches=14, cost_usd=0.27), None),
    (_usage(searches=15), "searches"),
    (_usage(cost_usd=0.28), "budget"),          # 70% of $0.40
])
def test_research_stop_reason(usage, expected):
    assert research_stop_reason(usage, LIMITS) == expected


def test_limits_from_env(monkeypatch):
    monkeypatch.setenv("COST_LIMIT_USD", "0.25")
    monkeypatch.setenv("MAX_LLM_CALLS", "10")
    limits = Limits.from_env()
    assert (limits.cost_usd, limits.max_llm_calls, limits.seconds) == (0.25, 10, 540)


def test_elapsed_seconds():
    now = datetime(2026, 11, 9, 12, 10, tzinfo=timezone.utc)
    assert elapsed_seconds("2026-11-09T12:00:00+00:00", now) == 600
    assert elapsed_seconds(None, now) == 0 and elapsed_seconds("garbage", now) == 0
    assert elapsed_seconds("2026-11-09T13:00:00+00:00", now) == 0      # future start: clamped


# --------------------------------------------------------------------------
# model callbacks
# --------------------------------------------------------------------------
def _ctx(agent_name, state):
    return SimpleNamespace(agent_name=agent_name, state=state)


def _now_iso(minus_seconds=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=minus_seconds)).isoformat(timespec="seconds")


def test_before_model_counts_allowed_calls():
    state = {"usage": new_usage(), "started_at": _now_iso()}
    assert limit_before_model(_ctx("researcher", state), None) is None
    assert limit_before_model(_ctx("judge", state), None) is None
    assert state["usage"]["llm_calls"] == 2


@pytest.mark.parametrize("over,state_extra,reason", [
    ({"llm_calls": 50}, {}, "llm_calls"),
    ({"cost_usd": 0.41}, {}, "cost"),
    ({}, {"started_at": _now_iso(minus_seconds=600)}, "time"),
])
def test_hard_stop_blocks_and_records(over, state_extra, reason):
    state = {"usage": _usage(**over), "started_at": _now_iso(), "research": "- old notes",
             **state_extra}
    response = limit_before_model(_ctx("researcher", state), None)
    assert response.content.parts[0].text == "- old notes"     # keeps previous research
    assert state["usage"]["hard_stop"] == reason
    assert state["usage"]["llm_calls"] == over.get("llm_calls", 0)   # blocked call not counted


def test_blocked_judge_returns_valid_schema_json():
    state = {"usage": _usage(cost_usd=1.0), "started_at": _now_iso()}
    text = limit_before_model(_ctx("judge", state), None).content.parts[0].text
    feedback = JudgeFeedback.model_validate_json(text)
    assert feedback.status == "fail" and "cost limit" in feedback.summary


def test_blocked_judge_keeps_previous_feedback():
    previous = {"status": "pass", "missing_sections": [], "unsourced_claims": [],
                "stale_news": [], "summary": "ok"}
    state = {"usage": _usage(cost_usd=1.0), "started_at": _now_iso(), "judge_feedback": previous}
    text = limit_before_model(_ctx("judge", state), None).content.parts[0].text
    assert json.loads(text) == previous


def test_blocked_writer_returns_last_draft_or_nothing():
    state = {"usage": _usage(cost_usd=1.0), "started_at": _now_iso()}
    assert limit_before_model(_ctx("writer", state), None).content.parts[0].text == ""
    check_dossier_format("# Draft", SimpleNamespace(state=state))
    assert limit_before_model(_ctx("writer", state), None).content.parts[0].text == "# Draft"


def test_research_stop_blocks_only_the_research_loop():
    state = {"usage": _usage(research_stop="searches"), "started_at": _now_iso(),
             "research": "- notes"}
    assert limit_before_model(_ctx("researcher", state), None).content.parts[0].text == "- notes"
    assert limit_before_model(_ctx("writer", state), None) is None      # the writer still runs
    assert state["usage"]["llm_calls"] == 1


def _response(text="ok", queries=None, partial=None):
    return SimpleNamespace(
        partial=partial,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1000, candidates_token_count=100, thoughts_token_count=200),
        grounding_metadata=(types.GroundingMetadata(web_search_queries=queries)
                            if queries is not None else None),
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        model_version="gemini-3.5-flash",
    )


def test_after_model_adds_usage_and_searches():
    state = {"usage": new_usage()}
    limit_after_model(_ctx("researcher", state), _response(queries=["q1", "q2"]))
    u = state["usage"]
    assert (u["input_tokens"], u["output_tokens"], u["thinking_tokens"]) == (1000, 100, 200)
    assert u["searches"] == 2 and u["cost_usd"] > 0


def test_after_model_uses_reported_searches_without_grounding():
    state = {"usage": new_usage()}
    limit_after_model(_ctx("researcher", state), _response(text="Searches performed: 6\n- x"))
    assert (state["usage"]["searches"], state["usage"]["searches_source"]) == (6, "model_reported")


def test_after_model_skips_partial_chunks():
    state = {"usage": new_usage()}
    limit_after_model(_ctx("writer", state), _response(partial=True))
    assert state["usage"] == new_usage()


# --------------------------------------------------------------------------
# EscalationChecker: research stops
# --------------------------------------------------------------------------
def _escalation(state):
    ctx = SimpleNamespace(invocation_id="inv-1", session=SimpleNamespace(state=state))

    async def collect():
        return [e async for e in EscalationChecker()._run_async_impl(ctx)]

    return asyncio.run(collect())[0].actions


@pytest.mark.parametrize("usage,reason", [
    (_usage(searches=15), "searches"),
    (_usage(cost_usd=0.30), "budget"),
])
def test_escalation_stops_research_on_limits(usage, reason):
    actions = _escalation({"usage": usage, "judge_feedback": {"status": "fail"}})
    assert actions.escalate is True
    assert actions.state_delta["usage"]["research_stop"] == reason


def test_escalation_on_hard_stop():
    actions = _escalation({"usage": _usage(hard_stop="cost"), "judge_feedback": {"status": "fail"}})
    assert actions.escalate is True


def test_escalation_continues_when_within_limits():
    actions = _escalation({"usage": _usage(searches=5, cost_usd=0.1),
                           "judge_feedback": {"status": "fail"}})
    assert not actions.escalate and "usage" not in actions.state_delta


# --------------------------------------------------------------------------
# finalize_run: usage and stops in result.json
# --------------------------------------------------------------------------
DOSSIER = """# X

## Snapshot
- Fact one, with detail. (https://x.example/a)

## Recent news
- [Pending]

## Tech signals
- [Pending]

## Key people
- [Pending]

## Likely pains
- [Pending]

## Metacortex angle
- Point.

## What changed
- [Pending]
"""


def _state(**extra):
    return {"company": "X", "domain": "x.example", "run_id": "r1",
            "started_at": "2026-11-09T12:00:00+00:00", "trigger": "manual", "iterations": 1,
            "research": "- a (source: https://x.example/a) (quote: \"a\")",
            "judge_feedback": {"status": "pass"}, "loaded_cases": [], "case_study_urls": [],
            "seller": "Metacortex", "angle_section": "Metacortex angle",
            **extra}


def _finalize(state):
    finalize_run(SimpleNamespace(state=state, user_content=None))
    return state


def test_finalize_writes_usage(tmp_storage):
    usage = _usage(llm_calls=7, input_tokens=50_000, cost_usd=0.2, searches=6,
                   searches_source="grounding")
    r = _finalize(_state(dossier_md=DOSSIER, usage=usage))["result"]
    assert r["status"] == "ok"
    assert r["usage"]["llm_calls"] == 7 and r["usage"]["searches"] == 6
    assert r["usage"]["hard_stop"] is None and r["usage"]["elapsed_seconds"] >= 0


def test_finalize_hard_stop_with_draft_is_partial(tmp_storage):
    r = _finalize(_state(dossier_md=DOSSIER, usage=_usage(hard_stop="cost", cost_usd=0.41)))["result"]
    assert r["status"] == "partial"
    assert r["errors"][0] == {"source": "hard_stop", "message": "cost limit reached ($0.40)"}
    assert r["pending_human"][0]["id"] == "hard-stop"


def test_finalize_hard_stop_without_dossier_writes_failed_result(tmp_storage):
    state = _finalize(_state(dossier_md="", usage=_usage(hard_stop="time")))
    r = json.loads(tmp_storage.read_text("outbox/2026-11-09/r1/result.json"))
    assert r == state["result"]
    assert r["status"] == "failed" and r["data"] is None
    assert r["errors"][0]["source"] == "hard_stop" and "time limit" in r["errors"][0]["message"]
    assert tmp_storage.read_text("outbox/2026-11-09/r1/report.md") is None
    assert tmp_storage.read_text("state/dossiers/x.example.json") is None   # memory untouched


def test_finalize_research_stop_is_noted_but_not_an_error(tmp_storage):
    r = _finalize(_state(dossier_md=DOSSIER, usage=_usage(research_stop="searches")))["result"]
    assert r["status"] == "ok" and r["errors"] == []
    assert r["pending_human"][0]["id"] == "research-stopped"


def test_every_llm_agent_has_the_limit_callbacks():
    for a in (agent_module.researcher, agent_module.judge, agent_module.writer):
        assert a.before_model_callback is limit_before_model
        assert a.after_model_callback is limit_after_model
