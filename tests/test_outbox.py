"""Offline tests for dossier_agent/outbox.py and finalize_run."""
import json
from types import SimpleNamespace

import pytest

from dossier_agent.agent import finalize_run, init_state
from dossier_agent.memory import load_previous_dossier
from pydantic import ValidationError

from dossier_agent.outbox import (
    add_sources, build_data, build_pending_human, build_result, check_run_id,
    extract_seller_cases, extract_news, extract_pains, outbox_prefix, pending_sections,
    unsourced_count, write_outbox,
)

CASE_URL = "https://example.com/case-studies/event-analytics-scaling"
ANGLE = "Metacortex angle"
CASES = [
    {"id": "cs-01", "title": "Scaling an event-analytics pipeline", "url": CASE_URL},
    {"id": "cs-02", "title": "Warehouse migration", "url": "https://example.com/case-studies/dwh"},
]

DOSSIER_MD = f"""# Plausible Analytics

## Snapshot
- Team of 11. (https://plausible.io/about)

## Recent news
- Released version 3.0. (date: 2026-10-01) (https://plausible.io/blog/v3)
- Opened an office in Tallinn. (date: 2026-09-15) (https://plausible.io/blog/office)

## Tech signals
- [Pending]

## Key people
- Uku Taht, Co-founder (https://plausible.io/about)

## Likely pains
- Hit limits of vertical scaling. (https://plausible.io/jobs)
- Hypothesis: ClickHouse is an operational burden (based on: limits of vertical scaling (single node)) (https://plausible.io/jobs)
- Hypothesis: hiring is slow (based on: one open role) (https://plausible.io/jobs#open)
- Hypothesis: small team limits release speed (based on: team of 11) (https://plausible.io/about)

## Metacortex angle
- Scaling help fits their pain (based on: limits of vertical scaling).
- Case: event-analytics scaling ({CASE_URL})
- Question: who owns ClickHouse today?

## What changed
- [Pending]
"""

RESEARCH = """## Snapshot
- Team of 11. (source: https://plausible.io/about) (quote: "team")
- News. (source: https://plausible.io/blog/v3) (quote: "v3")
- News. (source: https://plausible.io/blog/office) (quote: "office")
- Pain. (source: https://plausible.io/jobs) (quote: "limits")
- Pain. (source: https://plausible.io/jobs#open) (quote: "open")
"""


# --------------------------------------------------------------------------
# extraction from the dossier
# --------------------------------------------------------------------------
def test_extract_news():
    assert extract_news(DOSSIER_MD) == [
        {"date": "2026-10-01", "title": "Released version 3.0.", "url": "https://plausible.io/blog/v3"},
        {"date": "2026-09-15", "title": "Opened an office in Tallinn.",
         "url": "https://plausible.io/blog/office"},
    ]


def test_extract_news_pending():
    assert extract_news(DOSSIER_MD.replace(
        "- Released version 3.0. (date: 2026-10-01) (https://plausible.io/blog/v3)\n"
        "- Opened an office in Tallinn. (date: 2026-09-15) (https://plausible.io/blog/office)",
        "- [Pending]")) == []


def test_extract_pains():
    assert extract_pains(DOSSIER_MD) == [
        {"hypothesis": "ClickHouse is an operational burden", "evidence_url": "https://plausible.io/jobs"},
        {"hypothesis": "hiring is slow", "evidence_url": "https://plausible.io/jobs#open"},
        {"hypothesis": "small team limits release speed", "evidence_url": "https://plausible.io/about"},
    ]   # the plain fact in Likely pains is not a hypothesis


def test_extract_pains_without_url():
    md = "# X\n\n## Likely pains\n- Hypothesis: something (based on: a fact)\n"
    assert extract_pains(md) == [{"hypothesis": "something", "evidence_url": None}]


def test_extract_seller_cases():
    assert extract_seller_cases(DOSSIER_MD, CASES, angle_section=ANGLE) == [
        {"id": "cs-01", "title": "Scaling an event-analytics pipeline", "url": CASE_URL},
    ]
    assert extract_seller_cases(DOSSIER_MD, [], angle_section=ANGLE) == []
    # a case URL under another seller's heading is not cited for this seller
    assert extract_seller_cases(DOSSIER_MD, CASES, angle_section="Initech angle") == []


def test_case_url_outside_angle_is_not_a_cited_case():
    md = DOSSIER_MD.replace(f"- Case: event-analytics scaling ({CASE_URL})\n", "") \
                   .replace("## What changed\n- [Pending]", f"## What changed\n- See {CASE_URL}")
    assert extract_seller_cases(md, CASES, angle_section=ANGLE) == []


def test_pending_sections():
    assert pending_sections(DOSSIER_MD) == ["Tech signals"]   # What changed is not a fact section
    assert pending_sections("") == []


@pytest.mark.parametrize("counts,expected", [
    ({"supported": 15, "not_found": 2, "missing_quote": 1, "unreachable": 4,
      "pending": 2, "hypothesis": 1, "weak_support": 5}, 3),
    ({"missing_source": 1, "dead_link": 1}, 2),
    ({}, 0),
    (None, None),
    ("oops", None),
])
def test_unsourced_count(counts, expected):
    assert unsourced_count(counts) == expected


# --------------------------------------------------------------------------
# pending_human: {id, question, source_ref}
# --------------------------------------------------------------------------
def _questions(items):
    return [i["question"] for i in items]


def test_pending_human_on_pass_lists_only_empty_sections():
    fb = {"status": "pass", "unsourced_claims": ["ignored on pass"], "summary": "ok"}
    assert build_pending_human(fb, DOSSIER_MD) == [
        {"id": "no-data-tech-signals", "question": "No data: Tech signals",
         "source_ref": "Tech signals"},
    ]


def test_pending_human_on_fail_lists_judge_problems():
    fb = json.dumps({"status": "fail", "missing_sections": ["Key people"],
                     "unsourced_claims": ["Raised $5M (https://news.example/a)."],
                     "stale_news": ["2024 launch"], "summary": "fix"})
    items = build_pending_human(fb, DOSSIER_MD)
    assert [i["id"] for i in items] == [
        "missing-section-key-people", "unsourced-1", "stale-news-1", "no-data-tech-signals"]
    assert items[0]["source_ref"] == "Key people"
    assert items[1]["source_ref"] == "https://news.example/a"
    assert items[2]["source_ref"] == ""
    assert items[1]["question"] == "Unsourced claim: Raised $5M (https://news.example/a)."


def test_pending_human_on_fail_without_lists_uses_summary():
    fb = {"status": "fail", "summary": "Dates are not verified."}
    first = build_pending_human(fb, DOSSIER_MD)[0]
    assert first["id"] == "judge-not-passed"
    assert first["question"] == "Judge did not pass the research: Dates are not verified."
    assert build_pending_human(None, DOSSIER_MD)[0]["question"] == "Judge did not pass the research."


def test_pending_human_ids_are_unique():
    fb = {"status": "fail", "unsourced_claims": ["a", "b", "c"], "stale_news": ["d", "e"]}
    ids = [i["id"] for i in build_pending_human(fb, DOSSIER_MD)]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
# result.json and outbox
# --------------------------------------------------------------------------
def test_build_data():
    data = build_data(
        company="Plausible Analytics", domain="plausible.io", iterations=2,
        judge_feedback={"status": "pass"}, dossier_md=DOSSIER_MD,
        verification_counts={"supported": 5, "not_found": 1},
        case_studies=CASES, seller="Metacortex", previous_dossier_date="",
    )
    assert data["judge_status"] == "pass"
    assert data["iterations"] == 2
    assert data["facts_count"] == 5          # hypotheses and [Pending] are not facts
    assert data["unsourced_count"] == 1
    assert len(data["news"]) == 2 and len(data["pains"]) == 3
    assert data["seller"] == "Metacortex" and data["seller_cases"][0]["id"] == "cs-01"
    assert data["previous_dossier_date"] is None
    assert list(data) == ["company", "domain", "iterations", "judge_status", "facts_count",
                          "unsourced_count", "news", "pains", "seller", "seller_cases",
                          "previous_dossier_date"]


def test_build_data_judge_unknown_is_fail():
    data = build_data(company="X", domain="x.com", iterations=3, judge_feedback=None,
                      dossier_md="", verification_counts=None,
                      case_studies=[], seller="Metacortex",
                      previous_dossier_date=None)
    assert data["judge_status"] == "fail"


def _envelope(**over):
    args = dict(agent="prospect-dossier", run_id="r1", trigger="manual",
                started_at="2026-11-09T12:00:00+00:00", status="failed",
                pending_human=[], errors=[{"source": "service", "message": "boom"}],
                usage=None, data=None)
    args.update(over)
    return build_result(**args)


def test_build_result_envelope():
    r = _envelope()
    assert list(r) == ["agent", "run_id", "status", "trigger", "started_at",
                       "items_processed", "pending_human", "errors", "usage", "data"]
    assert r["items_processed"] == 1
    assert r["errors"] == [{"source": "service", "message": "boom"}]


@pytest.mark.parametrize("over", [
    {"status": "done"},
    {"trigger": "scheduler"},
    {"errors": ["a plain string"]},
    {"pending_human": ["a plain string"]},
    {"pending_human": [{"id": "x"}]},                          # no question
    {"data": {"company": "X"}},                                # incomplete data
])
def test_build_result_rejects_off_spec(over):
    with pytest.raises(ValidationError):
        _envelope(**over)


@pytest.mark.parametrize("run_id", ["20261109T120000Z-a1b2c3d4", "run_1", "a.b-c",
                                    "0b9c6f1e-3d5a-4c51-9a33-7c2a1f0e8d42"])
def test_valid_run_ids(run_id):
    assert check_run_id(run_id) == run_id


@pytest.mark.parametrize("run_id", ["", "../x", "a/b", ".hidden", "a..b", "a b", None, 7, "x" * 200])
def test_invalid_run_ids(run_id):
    with pytest.raises(ValueError):
        check_run_id(run_id)


def test_outbox_prefix():
    assert outbox_prefix("2026-11-09T23:59:59+00:00", "r1") == "outbox/2026-11-09/r1"
    with pytest.raises(ValueError):
        outbox_prefix("yesterday", "r1")


def test_write_outbox(tmp_storage):
    write_outbox("outbox/2026-11-09/r1", "# X", {"status": "ok"}, tmp_storage)
    assert tmp_storage.read_text("outbox/2026-11-09/r1/report.md") == "# X"
    assert json.loads(tmp_storage.read_text("outbox/2026-11-09/r1/result.json")) == {"status": "ok"}


def test_write_outbox_without_report(tmp_storage):
    write_outbox("outbox/2026-11-09/r2", None, {"status": "failed"}, tmp_storage)
    assert tmp_storage.read_text("outbox/2026-11-09/r2/report.md") is None
    assert tmp_storage.read_text("outbox/2026-11-09/r2/result.json")


# --------------------------------------------------------------------------
# finalize_run end to end (fake CallbackContext)
# --------------------------------------------------------------------------
def _state(**extra):
    return {
        "company": "Plausible Analytics", "domain": "plausible.io", "run_id": "r1",
        "started_at": "2026-11-09T12:00:00+00:00", "trigger": "inbox",
        "iterations": 1, "research": RESEARCH, "dossier_md": DOSSIER_MD,
        "loaded_cases": CASES, "case_study_urls": [c["url"] for c in CASES],
        "seller": "Metacortex", "angle_section": ANGLE,
        "verification_counts": {"supported": 5}, "previous_dossier_date": "2026-10-29",
        "judge_feedback": {"status": "pass", "summary": "ok"}, **extra,
    }


def _run(state):
    finalize_run(SimpleNamespace(state=state, user_content=None))
    return state


def test_finalize_ok(tmp_storage):
    state = _run(_state())
    result = json.loads(tmp_storage.read_text("outbox/2026-11-09/r1/result.json"))
    assert result == state["result"]
    assert result["status"] == "ok"
    assert result["agent"] == "prospect-dossier" and result["trigger"] == "inbox"
    assert result["errors"] == [] and result["usage"]["hard_stop"] is None
    assert _questions(result["pending_human"]) == ["No data: Tech signals"]
    assert result["data"]["previous_dossier_date"] == "2026-10-29"
    assert result["data"]["unsourced_count"] == 0
    assert result["data"]["news"][0] == {"date": "2026-10-01", "title": "Released version 3.0.",
                                         "url": "https://plausible.io/blog/v3"}
    assert result["data"]["pains"][1]["evidence_url"] == "https://plausible.io/jobs#open"
    assert tmp_storage.read_text("outbox/2026-11-09/r1/report.md") == add_sources(DOSSIER_MD)
    assert state["outbox_prefix"] == "outbox/2026-11-09/r1"
    assert load_previous_dossier("plausible.io", tmp_storage)["judge_status"] == "pass"


def test_finalize_partial_after_judge_fail(tmp_storage):
    state = _run(_state(iterations=3, judge_feedback={
        "status": "fail", "unsourced_claims": ["Raised $5M"], "summary": "x"}))
    r = state["result"]
    assert r["status"] == "partial"
    assert r["data"]["iterations"] == 3 and r["data"]["judge_status"] == "fail"
    assert r["pending_human"][0]["question"] == "Unsourced claim: Raised $5M"
    assert load_previous_dossier("plausible.io", tmp_storage)["judge_status"] == "fail"


def test_finalize_partial_when_format_check_fails(tmp_storage):
    md = DOSSIER_MD.replace("(https://plausible.io/about)", "(https://plausible.io/invented)", 1)
    r = _run(_state(dossier_md=md))["result"]
    assert r["status"] == "partial"
    assert r["errors"][0]["source"] == "format_check"


def test_finalize_without_dossier_writes_nothing(tmp_storage):
    state = _run(_state(dossier_md=""))
    assert "result" not in state
    assert tmp_storage.read_text("outbox/2026-11-09/r1/result.json") is None
    assert load_previous_dossier("plausible.io", tmp_storage) is None


# --------------------------------------------------------------------------
# init_state: fields that the outbox needs
# --------------------------------------------------------------------------
REQ = json.dumps({"company": "Plausible Analytics", "domain": "plausible.io"})


def _init(state):
    from google.genai import types
    ctx = SimpleNamespace(state=state, user_content=types.Content(
        role="user", parts=[types.Part(text=REQ)]))
    return init_state(ctx)


def test_init_state_sets_run_fields():
    import uuid
    state = {}
    assert _init(state) is None
    assert state["trigger"] == "manual"
    assert state["iterations"] == 0
    assert state["started_at"].endswith("+00:00")
    assert str(uuid.UUID(state["run_id"])) == state["run_id"]


def test_init_state_keeps_service_fields():
    state = {"run_id": "svc-1", "trigger": "inbox", "started_at": "2026-11-09T10:00:00+00:00"}
    _init(state)
    assert (state["run_id"], state["trigger"], state["started_at"]) == \
        ("svc-1", "inbox", "2026-11-09T10:00:00+00:00")


def test_init_state_rejects_bad_run_id():
    state = {"run_id": "../../etc"}
    result = _init(state)
    assert result is not None and "run_id" in state["input_error"]


def test_init_state_rejects_bad_trigger():
    state = {"trigger": "scheduler"}
    result = _init(state)
    assert result is not None and "trigger" in state["input_error"]


# --------------------------------------------------------------------------
# item 5: soft minimum of hypotheses, Sources section
# --------------------------------------------------------------------------
ONE_HYPOTHESIS = DOSSIER_MD.replace(
    "- Hypothesis: hiring is slow (based on: one open role) (https://plausible.io/jobs#open)\n", ""
).replace(
    "- Hypothesis: small team limits release speed (based on: team of 11) (https://plausible.io/about)\n", ""
)


def test_few_hypotheses_go_to_pending_human():
    items = build_pending_human({"status": "pass"}, ONE_HYPOTHESIS)
    assert {"id": "few-pain-hypotheses", "question": "Few pain hypotheses: 1 (target 3-5)",
            "source_ref": "Likely pains"} in items


def test_no_few_hypotheses_note_when_pains_pending():
    md = "# X\n\n## Likely pains\n- [Pending]\n"
    assert _questions(build_pending_human({"status": "pass"}, md)) == ["No data: Likely pains"]


def test_add_sources_lists_unique_urls_in_order():
    report = add_sources(DOSSIER_MD)
    head, sources = report.split("## Sources\n")
    assert head.rstrip() == DOSSIER_MD.rstrip()
    assert sources.splitlines() == [
        "- https://plausible.io/about",
        "- https://plausible.io/blog/v3",
        "- https://plausible.io/blog/office",
        "- https://plausible.io/jobs",
        "- https://plausible.io/jobs#open",
        f"- {CASE_URL}",
    ]


def test_add_sources_replaces_model_written_sources():
    md = DOSSIER_MD.rstrip() + "\n\n## Sources\n- https://invented.example/x\n"
    report = add_sources(md)
    assert report.count("## Sources") == 1
    assert "invented.example" not in report


def test_add_sources_without_urls():
    assert add_sources("# X\n\n## Snapshot\n- [Pending]\n").endswith("## Sources\n- [Pending]\n")


def test_finalize_report_has_sources(tmp_storage):
    _run(_state())
    report = tmp_storage.read_text("outbox/2026-11-09/r1/report.md")
    assert report.startswith("# Plausible Analytics")
    assert "\n## Sources\n- https://plausible.io/about\n" in report
