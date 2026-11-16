"""Offline tests for storage.py, memory.py and the memory callbacks."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.genai import types

from dossier_agent import storage
from dossier_agent.agent import finalize_run, init_state, judge_status
from dossier_agent.memory import (
    build_record,
    dossier_key,
    extract_facts,
    format_prior_knowledge,
    load_previous_dossier,
    save_dossier,
)

DOSSIER_MD = """# Plausible Analytics
Note: the research did not fully pass verification; some topics may be incomplete.

## Snapshot
- Team of 11. (https://plausible.io/about)
- Bootstrapped, no investors. (https://plausible.io/about#funding)

## Recent news
- Released version 3.0. (date: 2026-10-01) (https://plausible.io/blog/v3)

## Tech signals
- [Pending]

## Key people
- Uku Taht, Co-founder (https://plausible.io/about)

## Likely pains
- Hit limits of vertical scaling. (https://plausible.io/jobs)
- Hypothesis: ClickHouse is an operational burden (based on: limits of vertical scaling) (https://plausible.io/jobs)

## Metacortex angle
- Offer data engineering help. (https://example.com/case-1)

## What changed
- [Pending]
"""

SAVED_AT = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def test_local_storage_roundtrip(tmp_path):
    s = storage.LocalStorage(tmp_path)
    assert s.read_text("state/dossiers/a.com.json") is None
    s.write_text("state/dossiers/a.com.json", "один")
    assert s.read_text("state/dossiers/a.com.json") == "один"
    s.write_text("state/dossiers/a.com.json", "two")       # overwrite
    assert s.read_text("state/dossiers/a.com.json") == "two"
    assert [p.name for p in (tmp_path / "state/dossiers").iterdir()] == ["a.com.json"]


@pytest.mark.parametrize("key", [
    "", "/etc/passwd", "../x", "state/../../x", "state//x", "./x", "state\\x",
])
def test_storage_rejects_bad_keys(tmp_path, key):
    s = storage.LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        s.write_text(key, "x")
    with pytest.raises(ValueError):
        s.read_text(key)


def test_get_storage_relative_root_is_under_the_project(monkeypatch):
    monkeypatch.setattr(storage, "_storage", None)
    monkeypatch.setenv("STORAGE_ROOT", "data/other")
    assert storage.get_storage().root == storage.ROOT_DIR / "data/other"


def test_get_storage_absolute_root(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "_storage", None)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    s = storage.get_storage()
    s.write_text("state/x.json", "{}")
    assert (tmp_path / "state/x.json").read_text() == "{}"


# --------------------------------------------------------------------------
# dossier key and facts
# --------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["plausible.io", "https://www.Plausible.IO/about", "PLAUSIBLE.io."])
def test_dossier_key_spellings(raw):
    assert dossier_key(raw) == "state/dossiers/plausible.io.json"


@pytest.mark.parametrize("raw", ["../../config", "a/../../b", "", "evil..com"])
def test_dossier_key_rejects_bad_domain(raw):
    with pytest.raises(ValueError):
        dossier_key(raw)


def test_extract_facts():
    facts = extract_facts(DOSSIER_MD)
    assert facts == [
        {"section": "Snapshot", "text": "Team of 11.", "url": "https://plausible.io/about", "date": None},
        {"section": "Snapshot", "text": "Bootstrapped, no investors.",
         "url": "https://plausible.io/about#funding", "date": None},
        {"section": "Recent news", "text": "Released version 3.0.",
         "url": "https://plausible.io/blog/v3", "date": "2026-10-01"},
        {"section": "Key people", "text": "Uku Taht, Co-founder",
         "url": "https://plausible.io/about", "date": None},
        {"section": "Likely pains", "text": "Hit limits of vertical scaling.",
         "url": "https://plausible.io/jobs", "date": None},
    ]   # no [Pending], no hypothesis, nothing from the angle section / What changed


def test_extract_facts_url_with_parentheses():
    md = "# X\n\n## Snapshot\n- A wiki fact. (https://en.wikipedia.org/wiki/Foo_(bar))\n"
    assert extract_facts(md)[0]["url"] == "https://en.wikipedia.org/wiki/Foo_(bar)"


def test_extract_facts_empty():
    assert extract_facts("") == []
    assert extract_facts("# X\n\n## Snapshot\n- [Pending]\n") == []


def test_build_record():
    rec = build_record("www.plausible.io", "run-1", "fail", DOSSIER_MD, saved_at=SAVED_AT)
    assert rec["domain"] == "plausible.io"
    assert rec["saved_at"] == "2026-10-29T12:00:00+00:00"
    assert rec["run_id"] == "run-1"
    assert rec["judge_status"] == "fail"
    assert len(rec["facts"]) == 5
    assert "dossier_md" not in rec


# --------------------------------------------------------------------------
# load / save
# --------------------------------------------------------------------------
def test_load_missing(tmp_storage):
    assert load_previous_dossier("plausible.io", tmp_storage) is None


def test_save_then_load(tmp_storage):
    rec = build_record("plausible.io", "run-1", "pass", DOSSIER_MD, saved_at=SAVED_AT)
    key = save_dossier("Plausible.io", rec, tmp_storage)
    assert key == "state/dossiers/plausible.io.json"
    assert load_previous_dossier("https://www.plausible.io", tmp_storage) == rec


def test_save_overwrites(tmp_storage):
    save_dossier("a.com", build_record("a.com", "r1", "pass", DOSSIER_MD, SAVED_AT), tmp_storage)
    save_dossier("a.com", build_record("a.com", "r2", "fail", "", SAVED_AT), tmp_storage)
    rec = load_previous_dossier("a.com", tmp_storage)
    assert rec["run_id"] == "r2" and rec["facts"] == []


@pytest.mark.parametrize("text", [
    "{not json",
    "",
    "[]",
    json.dumps({"saved_at": "2026-10-29"}),                      # no facts
    json.dumps({"facts": []}),                                   # no saved_at
    json.dumps({"saved_at": "2026-10-29", "facts": ["x"]}),      # bad fact
])
def test_load_corrupt_is_missing(tmp_storage, text):
    tmp_storage.write_text("state/dossiers/a.com.json", text)
    assert load_previous_dossier("a.com", tmp_storage) is None


def test_load_bad_domain(tmp_storage):
    with pytest.raises(ValueError):
        load_previous_dossier("../../config", tmp_storage)


# --------------------------------------------------------------------------
# prior_knowledge
# --------------------------------------------------------------------------
def test_format_prior_knowledge():
    rec = build_record("plausible.io", "run-1", "pass", DOSSIER_MD, saved_at=SAVED_AT)
    assert format_prior_knowledge(rec) == (
        "Previous dossier from 2026-10-29 (judge status: pass).\n"
        "## Snapshot\n"
        "- Team of 11. (https://plausible.io/about)\n"
        "- Bootstrapped, no investors. (https://plausible.io/about#funding)\n"
        "## Recent news\n"
        "- Released version 3.0. (date: 2026-10-01) (https://plausible.io/blog/v3)\n"
        "## Key people\n"
        "- Uku Taht, Co-founder (https://plausible.io/about)\n"
        "## Likely pains\n"
        "- Hit limits of vertical scaling. (https://plausible.io/jobs)"
    )


def test_format_prior_knowledge_empty():
    assert format_prior_knowledge(None) == ""
    rec = build_record("a.com", "r", "fail", "", saved_at=SAVED_AT)
    assert format_prior_knowledge(rec) == "Previous dossier from 2026-10-29 (judge status: fail)."


# --------------------------------------------------------------------------
# callbacks: init_state loads, finalize_run saves
# --------------------------------------------------------------------------
def _ctx(state, text=None):
    content = None if text is None else types.Content(role="user", parts=[types.Part(text=text)])
    return SimpleNamespace(state=state, user_content=content)


REQ = json.dumps({"company": "Plausible Analytics", "domain": "www.plausible.io"})


def test_init_state_without_previous_dossier():
    state = {}
    assert init_state(_ctx(state, REQ)) is None
    assert state["prior_knowledge"] == ""
    assert state["previous_dossier_date"] == ""
    assert state["run_id"]


def test_init_state_loads_previous_dossier(tmp_storage):
    save_dossier("plausible.io",
                 build_record("plausible.io", "old", "pass", DOSSIER_MD, SAVED_AT), tmp_storage)
    state = {}
    init_state(_ctx(state, REQ))
    assert state["previous_dossier_date"] == "2026-10-29"
    assert state["prior_knowledge"].startswith("Previous dossier from 2026-10-29")


def test_init_state_keeps_run_id_from_service():
    state = {"run_id": "service-run-7"}
    init_state(_ctx(state, REQ))
    assert state["run_id"] == "service-run-7"


def _run_state(**extra):
    return {"domain": "plausible.io", "company": "Plausible Analytics", "run_id": "r1",
            "started_at": "2026-11-09T12:00:00+00:00", "research": "",
            "seller": "Metacortex", "angle_section": "Metacortex angle", **extra}


def test_finalize_saves_memory_with_judge_status(tmp_storage):
    state = _run_state(dossier_md=DOSSIER_MD, judge_feedback={"status": "fail", "summary": "x"})
    finalize_run(_ctx(state))
    rec = load_previous_dossier("plausible.io", tmp_storage)
    assert rec["judge_status"] == "fail" and rec["run_id"] == "r1"
    assert len(rec["facts"]) == 5
    assert state["saved_dossier_key"] == "state/dossiers/plausible.io.json"


@pytest.mark.parametrize("dossier_md", [None, "", "   "])
def test_finalize_without_dossier_keeps_previous(tmp_storage, dossier_md):
    old = build_record("plausible.io", "old", "pass", DOSSIER_MD, SAVED_AT)
    save_dossier("plausible.io", old, tmp_storage)
    state = _run_state(run_id="new", dossier_md=dossier_md)
    finalize_run(_ctx(state))
    assert load_previous_dossier("plausible.io", tmp_storage) == old
    assert tmp_storage.read_text("outbox/2026-11-09/new/result.json") is None


@pytest.mark.parametrize("feedback,expected", [
    ({"status": "pass"}, "pass"),
    ({"status": "fail"}, "fail"),
    ('{"status": "pass"}', "pass"),
    ({"verdict": "pass"}, "unknown"),          # old field name is not accepted
    ("not json", "unknown"),
    (None, "unknown"),
    ({"status": "maybe"}, "unknown"),
])
def test_judge_status(feedback, expected):
    assert judge_status(feedback) == expected


def test_extract_facts_skips_hypotheses_with_url():
    """Hypotheses end with the URL of their evidence, but they are not facts:
    they must never get into the memory file."""
    md = ("# X\n\n## Likely pains\n"
          "- Hit limits of vertical scaling. (https://plausible.io/jobs)\n"
          "- Hypothesis: ClickHouse is a burden (based on: limits) (https://plausible.io/jobs)\n")
    facts = extract_facts(md)
    assert [f["text"] for f in facts] == ["Hit limits of vertical scaling."]
    assert not any("Hypothesis" in f["text"] for f in facts)
