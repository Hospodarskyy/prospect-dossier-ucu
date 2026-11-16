"""Offline tests: bot-challenge pages, per-iteration trace, trace.json, blocked-page notice."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from dossier_agent import agent as agent_module
from dossier_agent.agent import EscalationChecker, SourceVerifier, finalize_run
from dossier_agent.verification import (
    UNREACHABLE, Fact, fetch_page_text, looks_like_bot_challenge, verify_fact, verify_research,
)

CHALLENGE_HTML = ("<html><head><title>Just a moment...</title></head><body>"
                  "<p>Enable JavaScript and cookies to continue</p></body></html>")
ARTICLE_HTML = ("<html><head><title>About</title></head><body><p>Today Plausible is a team of 11. "
                + "We build privacy-friendly analytics. " * 20 + "</p></body></html>")


# --------------------------------------------------------------------------
# bot-challenge detection
# --------------------------------------------------------------------------
def test_challenge_page_is_detected():
    assert looks_like_bot_challenge(CHALLENGE_HTML, "Just a moment... Enable JavaScript and cookies")


def test_long_article_mentioning_captcha_is_not_a_challenge():
    text = "We explain how captcha works. " + "Long article text. " * 300
    assert not looks_like_bot_challenge("<html>" + text + "</html>", text)


def test_normal_page_is_not_a_challenge():
    assert not looks_like_bot_challenge(ARTICLE_HTML, "Today Plausible is a team of 11.")


def _fetch(status, html, content_type="text/html; charset=utf-8"):
    def handler(request):
        return httpx.Response(status, text=html, headers={"content-type": content_type})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_page_text("https://plausible.io/about", client)

    return asyncio.run(go())


@pytest.mark.parametrize("status", [200, 403, 503])
def test_fetch_marks_challenge_pages(status):
    page = _fetch(status, CHALLENGE_HTML)
    assert page.ok is False and page.error == f"bot_challenge (HTTP {status})"
    assert page.status_code == status and "Just a moment" in page.head


def test_fetch_keeps_head_of_normal_pages():
    page = _fetch(200, ARTICLE_HTML)
    assert page.ok and page.head.startswith("About Today Plausible is a team of 11.")
    assert len(page.head) <= 200


def test_fetch_plain_404_is_not_a_challenge():
    page = _fetch(404, "<html><body>Not Found</body></html>" + "x" * 4000)
    assert page.error == "HTTP 404" and page.status_code == 404


def test_blocked_fact_is_unreachable_and_flagged():
    fact = Fact(section="Snapshot", kind="fact", claim="Team of 11.", url="https://plausible.io/about",
                quote="Today Plausible is a team of 11.", date=None)
    verified = verify_fact(fact, _fetch(200, CHALLENGE_HTML))
    assert verified["status"] == UNREACHABLE and verified["blocked"] is True
    assert verified["http_status"] == 200 and "Just a moment" in verified["page_head"]


def test_counts_include_blocked():
    research = ('## Snapshot\n- Team of 11. (source: https://plausible.io/about) '
                '(quote: "Today Plausible is a team of 11.")\n')

    page = _fetch(200, CHALLENGE_HTML)

    async def fetch(url):
        return page

    result = asyncio.run(verify_research(research, fetch=fetch))
    assert result["counts"]["unreachable"] == 1 and result["counts"]["blocked"] == 1


# --------------------------------------------------------------------------
# per-iteration trace in state
# --------------------------------------------------------------------------
def _run_agent(agent, state):
    ctx = SimpleNamespace(invocation_id="inv-1", session=SimpleNamespace(state=state))

    async def collect():
        return [e async for e in agent._run_async_impl(ctx)]

    return asyncio.run(collect())[0].actions.state_delta


def test_source_verifier_appends_an_iteration(monkeypatch, tmp_path):
    async def fake(research, cache_dir=None):
        return {"status": "ok", "counts": {"supported": 1}, "facts": [
            {"section": "Snapshot", "claim": "x", "url": "https://a.example", "final_url": "https://a.example",
             "status": "supported", "weak_support": False, "detail": "", "date": None,
             "date_check": None, "http_status": 200, "fetch_error": None, "page_head": "About",
             "blocked": False, "excerpt": "long text that is not traced"}]}
    monkeypatch.setattr(agent_module, "verify_research", fake)
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    state = {"research": "- notes", "iterations": 1,
             "trace": [{"iteration": 1, "research": "- old"}]}
    delta = _run_agent(SourceVerifier(name="source_verifier"), state)
    trace = delta["trace"]
    assert [t["iteration"] for t in trace] == [1, 2]
    assert trace[1]["research"] == "- notes" and trace[1]["verification_counts"] == {"supported": 1}
    assert trace[1]["facts"][0]["page_head"] == "About" and "excerpt" not in trace[1]["facts"][0]


def test_escalation_checker_adds_the_judge_answer():
    state = {"judge_feedback": {"status": "fail", "summary": "fix"},
             "trace": [{"iteration": 1, "research": "- notes"}]}
    delta = _run_agent(EscalationChecker(), state)
    assert delta["trace"][-1]["judge_feedback"] == {"status": "fail", "summary": "fix"}


# --------------------------------------------------------------------------
# finalize: trace.json and the blocked-pages notice
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
TRACE = [{"iteration": 1, "research": "- a", "facts": [
    {"url": "https://g.example/redirect1", "final_url": "https://plausible.io/docs/authors", "blocked": True},
    {"url": "https://g.example/redirect2", "final_url": "https://plausible.io/docs/authors", "blocked": True},
    {"url": "https://x.example/a", "final_url": "https://x.example/a", "blocked": False},
], "judge_feedback": {"status": "pass"}}]


def _state(**extra):
    return {"company": "X", "domain": "x.example", "run_id": "r1",
            "started_at": "2026-11-09T12:00:00+00:00", "trigger": "inbox", "iterations": 1,
            "research": "- a (source: https://x.example/a) (quote: \"a\")", "dossier_md": DOSSIER,
            "judge_feedback": {"status": "pass"}, "loaded_cases": [], "case_study_urls": [],
            "seller": "Metacortex", "angle_section": "Metacortex angle",
            "trace": TRACE, **extra}


def test_finalize_writes_trace_json(tmp_storage):
    state = _state()
    finalize_run(SimpleNamespace(state=state, user_content=None))
    trace = json.loads(tmp_storage.read_text("outbox/2026-11-09/r1/trace.json"))
    assert trace["run_id"] == "r1" and trace["iterations"] == TRACE


def test_finalize_reports_blocked_pages(tmp_storage):
    state = _state()
    finalize_run(SimpleNamespace(state=state, user_content=None))
    r = state["result"]
    assert r["usage"]["blocked_pages"] == 1                       # one page, two facts
    note = r["pending_human"][0]
    assert note["id"] == "blocked-pages" and note["source_ref"] == "https://plausible.io/docs/authors"


def test_finalize_without_blocked_pages(tmp_storage):
    state = _state(trace=[{"iteration": 1, "facts": [{"url": "https://x.example/a", "blocked": False}]}])
    finalize_run(SimpleNamespace(state=state, user_content=None))
    assert state["result"]["usage"]["blocked_pages"] == 0
    assert not any(p["id"] == "blocked-pages" for p in state["result"]["pending_human"])
