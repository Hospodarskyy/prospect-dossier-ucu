"""Offline tests: Google redirect links are replaced with real page URLs in
everything written out (report.md, result.json data, memory)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from dossier_agent import agent as agent_module
from dossier_agent.agent import SourceVerifier, finalize_run
from dossier_agent.memory import load_previous_dossier
from dossier_agent.outbox import replace_urls
from dossier_agent.verification import resolved_urls

R1 = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA1tU6JaPNzpQ="
R2 = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBBxZkQ="
R3 = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/CCC=="


# --------------------------------------------------------------------------
# resolved_urls(verification result)
# --------------------------------------------------------------------------
def test_resolved_urls_maps_loaded_redirects():
    result = {"facts": [
        {"url": R1, "final_url": "https://plausible.io/about", "status": "supported"},
        {"url": R2, "final_url": "https://plausible.io/jobs", "status": "not_found"},
        {"url": R3, "final_url": "https://blocked.example/x", "status": "unreachable"},
        {"url": "https://dead.example/a", "final_url": "https://dead.example/b", "status": "dead_link"},
        {"url": "https://plausible.io/blog", "final_url": "https://plausible.io/blog",
         "status": "supported"},                                   # unchanged
        {"url": None, "final_url": None, "status": "missing_source"},
        {"url": "https://x.example", "final_url": None, "status": "unreachable"},
    ]}
    assert resolved_urls(result) == {
        R1: "https://plausible.io/about",
        R2: "https://plausible.io/jobs",       # page loaded, quote not found: URL still real
    }


@pytest.mark.parametrize("result", [{}, {"facts": []}, {"status": "parse_error", "facts": []}])
def test_resolved_urls_empty(result):
    assert resolved_urls(result) == {}


# --------------------------------------------------------------------------
# replace_urls
# --------------------------------------------------------------------------
def test_replace_urls():
    text = f"- Fact. ({R1})\n- Other. ({R2})\n- Kept. (https://example.com/case)"
    out = replace_urls(text, {R1: "https://plausible.io/about", R2: "https://plausible.io/jobs"})
    assert out == ("- Fact. (https://plausible.io/about)\n- Other. (https://plausible.io/jobs)\n"
                   "- Kept. (https://example.com/case)")


def test_replace_urls_longer_key_first():
    short, long_ = "https://r.example/a", "https://r.example/ab"
    out = replace_urls(f"({long_}) ({short})", {short: "https://one.example", long_: "https://two.example"})
    assert out == "(https://two.example) (https://one.example)"


@pytest.mark.parametrize("mapping", [None, {}, "oops", {R1: None}, {"": "https://x.example"}])
def test_replace_urls_ignores_bad_mapping(mapping):
    assert replace_urls(f"({R1})", mapping) == f"({R1})"


# --------------------------------------------------------------------------
# SourceVerifier stores the mapping (verify_research stubbed: no network)
# --------------------------------------------------------------------------
def _run_verifier(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(agent_module, "verify_research", fake)
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    ctx = SimpleNamespace(invocation_id="inv-1", session=SimpleNamespace(state={"research": "- x"}))

    async def collect():
        return [e async for e in SourceVerifier(name="source_verifier")._run_async_impl(ctx)]

    return asyncio.run(collect())[0].actions.state_delta


def test_source_verifier_stores_resolved_urls(monkeypatch, tmp_path):
    async def fake(research, cache_dir=None):
        return {"status": "ok", "counts": {"supported": 1}, "facts": [
            {"url": R1, "final_url": "https://plausible.io/about", "status": "supported",
             "section": "Snapshot", "claim": "x", "weak_support": False, "date_check": None}]}
    delta = _run_verifier(monkeypatch, tmp_path, fake)
    assert delta["resolved_urls"] == {R1: "https://plausible.io/about"}
    assert delta["verification_counts"] == {"supported": 1}


def test_source_verifier_error_gives_empty_mapping(monkeypatch, tmp_path):
    async def boom(research, cache_dir=None):
        raise RuntimeError("network down")
    delta = _run_verifier(monkeypatch, tmp_path, boom)
    assert delta["resolved_urls"] == {} and delta["verification_counts"] is None
    assert "ERROR" in delta["verification"]


# --------------------------------------------------------------------------
# finalize_run: output uses real URLs, checks still use research URLs
# --------------------------------------------------------------------------
CASE_URL = "https://example.com/case-studies/event-analytics-scaling"
DOSSIER_MD = f"""# Plausible Analytics

## Snapshot
- Team of 11. ({R1})

## Recent news
- Released version 3.0. (date: 2026-10-01) ({R3})

## Tech signals
- [Pending]

## Key people
- Uku Taht, Co-founder ({R1})

## Likely pains
- Hit limits of vertical scaling. ({R2})
- Hypothesis: ClickHouse is a burden (based on: limits) ({R2})
- Hypothesis: hiring is slow (based on: team of 11) ({R1})
- Hypothesis: small team (based on: team of 11) ({R1})

## Metacortex angle
- Case ({CASE_URL})

## What changed
- [Pending]
"""
RESEARCH = f"- a (source: {R1}) (quote: \"a\")\n- b (source: {R2}) (quote: \"b\")\n" \
           f"- c (source: {R3}) (quote: \"c\")\n"
MAPPING = {R1: "https://plausible.io/about", R2: "https://plausible.io/jobs"}   # R3 unresolved


def _state(**extra):
    return {
        "company": "Plausible Analytics", "domain": "plausible.io", "run_id": "r1",
        "started_at": "2026-11-09T12:00:00+00:00", "trigger": "manual", "iterations": 1,
        "research": RESEARCH, "dossier_md": DOSSIER_MD, "resolved_urls": MAPPING,
        "loaded_cases": [{"id": "cs-01", "title": "T", "url": CASE_URL}],
        "case_study_urls": [CASE_URL], "seller": "Metacortex", "angle_section": "Metacortex angle", "verification_counts": {"supported": 3},
        "judge_feedback": {"status": "pass"}, **extra,
    }


def test_finalize_writes_real_urls(tmp_storage):
    state = _state()
    finalize_run(SimpleNamespace(state=state, user_content=None))
    r = state["result"]
    assert r["status"] == "ok" and r["errors"] == []          # checks used research URLs
    report = tmp_storage.read_text("outbox/2026-11-09/r1/report.md")
    assert R1 not in report and R2 not in report
    assert "- Team of 11. (https://plausible.io/about)" in report
    assert report.split("## Sources\n")[1].splitlines() == [
        "- https://plausible.io/about", f"- {R3}", "- https://plausible.io/jobs", f"- {CASE_URL}"]
    assert r["data"]["news"][0]["url"] == R3                   # no real URL known: kept
    assert {p["evidence_url"] for p in r["data"]["pains"]} == {
        "https://plausible.io/jobs", "https://plausible.io/about"}
    memory_urls = {f["url"] for f in load_previous_dossier("plausible.io", tmp_storage)["facts"]}
    assert memory_urls == {"https://plausible.io/about", "https://plausible.io/jobs", R3}
    assert state["dossier_md"] == DOSSIER_MD                    # state keeps the original


def test_finalize_without_mapping_keeps_urls(tmp_storage):
    state = _state(resolved_urls=None)
    finalize_run(SimpleNamespace(state=state, user_content=None))
    assert R1 in tmp_storage.read_text("outbox/2026-11-09/r1/report.md")
