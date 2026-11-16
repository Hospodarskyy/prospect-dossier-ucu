"""Streamlit demo: saved runs, graph steps and the app itself (offline, no model)."""
import json
import pathlib
from types import SimpleNamespace

import pytest

from demo_app.component import graph_html, node_cards
from demo_app.graph import (
    GraphState, Step, final_state, graph_dot, replay_states, steps_from_event, steps_from_run,
)
from demo_app.runs import list_runs, load_run

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = "# Acme\n\n## Snapshot\n- Acme sells anvils. (https://a.io)\n\n## Recent news\n- [Pending]\n"


def _result(run_id, started_at, status="ok", company="Acme", cost=0.1, iterations=1):
    return {"agent": "prospect-dossier", "run_id": run_id, "status": status,
            "started_at": started_at, "pending_human": [], "errors": [],
            "usage": {"llm_calls": 5, "searches": 4, "cost_usd": cost, "elapsed_seconds": 150.0,
                      "hard_stop": None, "research_stop": None},
            "data": {"company": company, "domain": "acme.io", "iterations": iterations,
                     "judge_status": "pass"}}


def _write_run(outbox, run_id, started_at, result=None, report="# Acme\n", trace=None):
    folder = outbox / started_at[:10] / run_id
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(
        json.dumps(result if result is not None else _result(run_id, started_at)))
    if report is not None:
        (folder / "report.md").write_text(report)
    if trace is not None:
        (folder / "trace.json").write_text(json.dumps(trace))
    return folder


def _iteration(n, verdict, research="Searches performed: 3 (queries: a; b; c)\n"
               "- fact one (source: https://a.io) (quote: \"x\")\n- fact two (source: https://b.io)"):
    return {"iteration": n, "research": research,
            "verification_counts": {"pending": 1, "supported": 2},
            "verification_report": "SOURCE VERIFICATION ...",
            "facts": [{"section": "Snapshot", "claim": "fact one", "status": "supported"}],
            "judge_feedback": {"status": verdict, "summary": f"verdict {verdict}"}}


# --------------------------------------------------------------------------
# saved runs
# --------------------------------------------------------------------------
def test_list_runs_newest_first_and_a_run_in_two_sources_once(tmp_path):
    local, demo = tmp_path / "local", tmp_path / "demo"
    _write_run(local, "run-a", "2026-11-11T10:00:00+00:00")
    _write_run(local, "run-b", "2026-11-12T10:00:00+00:00")
    _write_run(demo, "run-a", "2026-11-11T10:00:00+00:00")      # the same run, copied
    _write_run(demo, "run-c", "2026-11-10T10:00:00+00:00")
    runs = list_runs([("local", local), ("demo", demo)])
    assert [(r.run_id, r.source) for r in runs] == [
        ("run-b", "local"), ("run-a", "local"), ("run-c", "demo")]


def test_list_runs_skips_broken_files_and_missing_folders(tmp_path):
    folder = _write_run(tmp_path, "run-a", "2026-11-11T10:00:00+00:00")
    (folder / "result.json").write_text("{not json")
    assert list_runs([("local", tmp_path), ("demo", tmp_path / "nope")]) == []


def test_old_run_without_usage_and_data_still_lists(tmp_path):
    result = {"run_id": "run-old", "status": "failed", "started_at": "2026-11-09T01:00:00+00:00",
              "usage": None, "data": None}
    _write_run(tmp_path, "run-old", "2026-11-09T01:00:00+00:00", result=result, report=None)
    (run,) = list_runs([("local", tmp_path)])
    assert run.company == "" and run.cost_usd is None
    assert run.label() == "2026-11-09 01:00 · run-old · failed · $ n/a · local"


def test_load_run_reports_missing_files_as_none(tmp_path):
    folder = _write_run(tmp_path, "run-a", "2026-11-11T10:00:00+00:00", report=None)
    run = load_run(folder)
    assert run["result"]["run_id"] == "run-a"
    assert run["report"] is None and run["trace"] is None


def test_sample_runs_in_demo_data_load_and_have_metacortex():
    runs = list_runs([("demo", ROOT / "demo-data" / "runs")])
    assert {r.domain for r in runs} >= {"plausible.io", "zorblax-dynamics.io"}
    for info in runs:
        run = load_run(info.path)
        assert run["result"]["data"]["seller"] == "Metacortex"
        assert "## Metacortex angle" in run["report"]
        assert run["trace"]["iterations"]


# --------------------------------------------------------------------------
# steps of a saved run
# --------------------------------------------------------------------------
def test_steps_from_trace_two_iterations():
    trace = {"iterations": [_iteration(1, "fail"), _iteration(2, "pass")]}
    steps = steps_from_run(_result("r", "2026-11-11T10:00:00+00:00"), trace, report=REPORT)
    assert [s.node for s in steps] == [
        "init_state",
        "researcher", "source_verifier", "judge", "escalation_checker",
        "researcher", "source_verifier", "judge", "escalation_checker",
        "writer", "finalize"]
    assert steps[1].text == "reports 3 searches, 2 facts with a source"
    assert dict(steps[1].info)["first fact"] == "fact one"
    assert steps[2].text == "supported 2 · pending 1"
    assert [s.outcome for s in steps if s.node == "judge"] == ["fail", "pass"]
    assert steps[4].text == "judge failed: next iteration"
    assert steps[8].text == "judge passed: on to the writer"
    assert steps[-1].outcome == "ok"


def test_steps_from_trace_last_fail_shows_the_stop_reason():
    result = _result("r", "2026-11-11T10:00:00+00:00", status="partial")
    result["usage"]["research_stop"] = "search limit (15) reached"
    steps = steps_from_run(result, {"iterations": [_iteration(1, "fail")]}, report=REPORT)
    assert steps[4].text == "stop: search limit (15) reached"


def test_steps_without_trace_use_the_iteration_count():
    result = _result("r", "2026-11-09T10:00:00+00:00", iterations=2)
    steps = steps_from_run(result, None, report=REPORT)
    assert [s.outcome for s in steps if s.node == "judge"] == ["fail", "pass"]
    assert steps[1].text == "no trace saved for this run"


def test_cited_case_studies_show_the_load_seller_cases_call():
    result = _result("r", "2026-11-11T10:00:00+00:00")
    result["data"]["seller_cases"] = [{"id": "cs-01"}, {"id": "cs-04"}]
    steps = steps_from_run(result, {"iterations": [_iteration(1, "pass")]}, report=REPORT)
    writer = [s for s in steps if s.node == "writer"]
    assert [(s.tool, s.text) for s in writer] == [
        ("load_seller_cases", "cites 2 case studies from load_seller_cases"),
        ("", "dossier written")]
    assert "load_seller_cases" in final_state(steps).done


def test_failed_run_without_report_has_no_writer_step():
    result = _result("r", "2026-11-11T10:00:00+00:00", status="failed")
    result["errors"] = [{"source": "limits", "message": "cost limit reached"}]
    steps = steps_from_run(result, {"iterations": [_iteration(1, "fail")]}, report=None)
    assert "writer" not in [s.node for s in steps]
    assert steps[-1].text == "status: failed; cost limit reached"


def test_iteration_cut_before_the_judge_stops_the_loop_steps():
    it = _iteration(1, "fail")
    del it["judge_feedback"]
    steps = steps_from_run(_result("r", "2026-11-11T10:00:00+00:00", status="failed"),
                           {"iterations": [it]}, report=None)
    assert [s.node for s in steps] == ["init_state", "researcher", "source_verifier", "finalize"]


# --------------------------------------------------------------------------
# graph state
# --------------------------------------------------------------------------
def test_a_new_iteration_resets_the_loop_nodes():
    gs = GraphState()
    for step in [Step("init_state", ""), Step("researcher", "", 1, tool="google_search"),
                 Step("source_verifier", "", 1), Step("judge", "", 1, outcome="fail"),
                 Step("escalation_checker", "", 1), Step("researcher", "", 2, tool="google_search")]:
        gs.apply(step)
    assert gs.iteration == 2 and gs.active == "researcher" and gs.active_tool == "google_search"
    assert "init_state" in gs.done and "judge" not in gs.done
    assert gs.verdicts == ["fail"]


def test_live_iterations_count_without_numbers_and_verdicts_follow():
    gs = GraphState()
    for verdict in ("fail", "pass"):
        gs.apply(Step("researcher", "searching", tool="google_search"))
        gs.apply(Step("researcher", "3 searches"))        # same node: same iteration
        gs.apply(Step("judge", "", outcome=verdict))
    assert gs.iteration == 2 and gs.verdicts == ["fail", "pass"]


def test_tool_calls_light_up_and_finish():
    gs = GraphState()
    gs.apply(Step("writer", "calls load_seller_cases", tool="load_seller_cases"))
    assert gs.active_tool == "load_seller_cases"
    gs.apply(Step("writer", "writing"))
    assert gs.active_tool is None and "load_seller_cases" in gs.done


def test_replay_ends_with_nothing_active_and_the_status():
    steps = steps_from_run(_result("r", "2026-11-11T10:00:00+00:00"),
                           {"iterations": [_iteration(1, "pass")]}, report=REPORT)
    states = replay_states(steps)
    assert len(states) == len(steps) + 1
    assert states[1].active == "researcher"
    last = final_state(steps)
    assert last.active is None and last.status == "ok"
    assert {"init_state", "writer", "finalize", "google_search"} <= last.done


def test_graph_dot_marks_the_active_node_and_the_iteration():
    gs = GraphState()
    gs.apply(Step("researcher", "", 2, tool="google_search"))
    dot = graph_dot(gs)
    assert dot.startswith("digraph pipeline {") and dot.rstrip().endswith("}")
    assert "iteration 2 of max 3" in dot
    active = [line for line in dot.splitlines() if "#ffd479" in line]
    assert len(active) == 2 and "researcher [" in active[0] and "google_search [" in active[1]


def test_graph_dot_shows_verdicts_and_final_status_colors():
    gs = final_state(steps_from_run(
        _result("r", "2026-11-11T10:00:00+00:00", status="partial"),
        {"iterations": [_iteration(1, "fail"), _iteration(2, "fail")]}, report=REPORT))
    dot = graph_dot(gs)
    assert "LLM · 1:fail 2:fail" in dot
    finalize = next(line for line in dot.splitlines() if line.strip().startswith("finalize ["))
    assert "#d98200" in finalize


# --------------------------------------------------------------------------
# live ADK events
# --------------------------------------------------------------------------
def _event(author, delta=None, escalate=None, calls=(), text=None, responses=()):
    content = SimpleNamespace(parts=[SimpleNamespace(text=text)]) if text else None
    return SimpleNamespace(
        author=author, content=content,
        actions=SimpleNamespace(state_delta=delta or {}, escalate=escalate),
        get_function_calls=lambda: [SimpleNamespace(name=n) for n in calls],
        get_function_responses=lambda: [SimpleNamespace(name=n, response=r) for n, r in responses])


@pytest.mark.parametrize("event, expected", [
    (_event("researcher"), [("researcher", "searching the web and writing facts", "")]),
    (_event("researcher", {"research": "Searches performed: 2\n- a (source: https://a.io)"}),
     [("researcher", "reports 2 searches, 1 facts with a source", "")]),
    (_event("source_verifier", {"verification_counts": {"supported": 4}}),
     [("source_verifier", "supported 4", "")]),
    (_event("source_verifier", {"verification_counts": None}),
     [("source_verifier", "verification failed", "")]),
    (_event("judge", {"judge_feedback": '{"status": "fail", "summary": "news is stale"}'}),
     [("judge", "verdict: fail", "fail")]),
    (_event("escalation_checker", {"iterations": 1}),
     [("escalation_checker", "judge failed: next iteration", "")]),
    (_event("escalation_checker", {"usage": {"research_stop": "cost 70%"}}, escalate=True),
     [("escalation_checker", "stop: cost 70%", "")]),
    (_event("writer", calls=["load_seller_cases", "check_dossier_format"]),
     [("writer", "calls load_seller_cases", ""), ("writer", "calls check_dossier_format", "")]),
    (_event("writer", responses=[("load_seller_cases", {"success": True, "cases": [{}, {}]})]),
     [("writer", "load_seller_cases returned 2 case studies", "")]),
    (_event("writer", responses=[("check_dossier_format", {"success": True, "message": "ok"})]),
     [("writer", "format check passed", "")]),
    (_event("writer", responses=[("check_dossier_format",
                                  {"success": False, "message": "missing section: Key people"})]),
     [("writer", "format check failed: missing section: Key people", "")]),
    (_event("writer", {"dossier_md": "# Acme"}), [("writer", "dossier written", "")]),
    (_event("writer"), [("writer", "", "")]),
    (_event("dossier_pipeline", text="Invalid request: domain is required"),
     [("init_state", "Invalid request: domain is required", "failed")]),
    (_event("dossier_pipeline", {"company": "Acme", "domain": "acme.io"}),
     [("init_state", "request parsed; seller file and previous dossier loaded", "")]),
    (_event("dossier_pipeline", {"result": {"status": "partial"}, "outbox_prefix": "outbox/x"}),
     [("finalize", "status: partial", "partial")]),
    (_event("dossier_pipeline"), []),
    (_event("user"), []),
])
def test_steps_from_event(event, expected):
    steps = steps_from_event(event)
    assert [(s.node, s.text.split(" (")[0], s.outcome) for s in steps] == expected


def test_researcher_and_writer_tool_steps():
    (step,) = steps_from_event(_event("researcher"))
    assert step.tool == "google_search"
    steps = steps_from_event(_event("writer", calls=["load_seller_cases"]))
    assert steps[0].tool == "load_seller_cases"


# --------------------------------------------------------------------------
# the Streamlit app (AppTest runs app.py without a browser; no model calls)
# --------------------------------------------------------------------------
def test_app_past_runs_page_renders_a_sample_run():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert at.sidebar.radio[0].value == "Past runs"
    assert at.sidebar.selectbox[0].options          # the sample runs
    plausible = next(r for r in list_runs([("demo", ROOT / "demo-data" / "runs")])
                     if r.domain == "plausible.io")
    at.sidebar.selectbox[0].set_value(str(plausible.path)).run()
    assert not at.exception
    assert at.header[0].value == "Plausible Analytics"
    assert any("Metacortex angle" in m.value for m in at.markdown)
    assert at.dataframe                             # facts table of the research iteration
    assert {"Dossier", "Research iterations", "Iteration 1", "result.json",
            "trace.json"} <= {t.label for t in at.tabs}


def test_app_new_run_page_shows_the_form():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value("New run").run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Company", "Domain"]


# --------------------------------------------------------------------------
# hover cards
# --------------------------------------------------------------------------
def _saved_run_steps():
    result = _result("r", "2026-11-11T10:00:00+00:00")
    result["data"].update(seller="Metacortex", previous_dossier_date="2026-11-09",
                          seller_cases=[{"id": "cs-01", "title": "Event analytics"}])
    result["usage"].update(cost_usd=0.1234, searches_source="grounding")
    result["pending_human"] = [{"id": "no-data-recent-news"}]
    trace = {"iterations": [_iteration(1, "fail"), _iteration(2, "pass")]}
    trace["iterations"][0]["judge_feedback"]["stale_news"] = ["old post from 2020"]
    return steps_from_run(result, trace, report=REPORT)


def test_cards_of_a_saved_run_show_the_state_values():
    info = final_state(_saved_run_steps()).info
    assert info["init_state"]["company"] == "Acme"
    assert info["init_state"]["previous dossier"] == "2026-11-09"
    assert info["init_state"]["seller"] == "Metacortex"
    assert info["researcher"] == {"iteration": "2", "searches reported": "3",
                                  "facts with a source": "2", "first fact": "fact one"}
    assert info["google_search"] == {"searches reported": "3"}
    assert info["source_verifier"]["verification"] == "supported 2 · pending 1"
    assert info["source_verifier"]["facts checked"] == "1"
    assert info["judge"]["status"] == "pass" and info["judge"]["stale news"] == "0"
    assert info["escalation_checker"] == {"iterations": "2",
                                          "decision": "judge passed: on to the writer"}
    assert info["load_seller_cases"] == {"cited cases": "cs-01 Event analytics"}
    assert info["writer"]["pending items"] == "1"
    assert info["writer"]["to check by hand"] == "1"
    assert info["finalize"]["cost"] == "$0.123"
    assert info["finalize"]["searches"] == "4 (grounding)"
    assert info["finalize"]["time"] == "150 s"


def test_cards_during_replay_show_the_iteration_on_screen():
    states = replay_states(_saved_run_steps())
    judge_1 = next(s for s in states if s.active == "judge" and s.iteration == 1)
    assert judge_1.info["judge"]["status"] == "fail"
    assert judge_1.info["judge"]["stale news"] == "1: old post from 2020"
    researcher_2 = next(s for s in states if s.active == "researcher" and s.iteration == 2)
    assert "judge" not in researcher_2.info          # iteration 2 has no verdict yet
    assert "writer" not in researcher_2.info


def test_cards_of_live_events():
    gs = GraphState()
    for event in [
        _event("dossier_pipeline", {"company": "Acme", "domain": "acme.io", "context": "",
                                    "seller": "Metacortex", "previous_dossier_date": ""}),
        _event("researcher", {"research": "Searches performed: 2\n- a (source: https://a.io)",
                              "usage": {"llm_calls": 1, "cost_usd": 0.01}}),
        _event("writer", calls=["load_seller_cases"]),
    ]:
        for step in steps_from_event(event):
            gs.apply(step)
    assert gs.info["init_state"] == {"company": "Acme", "domain": "acme.io",
                                     "seller": "Metacortex",
                                     "previous dossier": "none (first dossier)"}
    assert gs.info["researcher"]["model calls so far"] == "1"
    assert gs.info["researcher"]["cost so far"] == "$0.010"


def test_tool_call_arguments_and_answers_go_to_the_tool_card():
    call = SimpleNamespace(name="load_seller_cases",
                           args={"industry": "SaaS", "tech": ["ClickHouse", "Hetzner"]})
    event = SimpleNamespace(author="writer", content=None,
                            actions=SimpleNamespace(state_delta={}, escalate=None),
                            get_function_calls=lambda: [call])
    gs = GraphState()
    for step in steps_from_event(event):
        gs.apply(step)
    for step in steps_from_event(_event("writer", responses=[(
            "load_seller_cases", {"success": True, "cases": [{"id": "cs-01"}, {"id": "cs-03"}]})])):
        gs.apply(step)
    assert gs.info["load_seller_cases"] == {
        "industry": "SaaS", "tech": "ClickHouse, Hetzner",
        "answer": "load_seller_cases returned 2 case studies (cs-01, cs-03)"}


def test_long_values_are_shortened():
    long_summary = "word " * 100
    (step,) = steps_from_event(_event("judge", {"judge_feedback": {"status": "fail",
                                                                   "summary": long_summary}}))
    summary = dict(step.info)["summary"]
    assert len(summary) == 160 and summary.endswith("…")


def test_every_node_has_a_card_with_its_state():
    gs = GraphState()
    gs.apply(Step("init_state", "", info=(("company", "Acme"),)))
    gs.apply(Step("researcher", "", 1, tool="google_search"))
    cards = node_cards(gs)
    assert set(cards) == {"init_state", "researcher", "source_verifier", "judge",
                          "escalation_checker", "writer", "finalize", "google_search",
                          "load_seller_cases", "check_dossier_format"}
    assert cards["init_state"]["state"] == "done"
    assert cards["init_state"]["rows"] == [["company", "Acme"]]
    assert cards["researcher"]["state"] == "running"
    assert cards["writer"] == {"title": "writer", "kind": "LLM", "state": "not reached", "rows": []}


def test_graph_html_embeds_the_dot_and_cards_safely():
    gs = GraphState()
    gs.apply(Step("init_state", "", info=(("context", "</script><b>x</b>"),)))
    page = graph_html(gs, "light")
    assert "viz-global.js" in page and "@viz-js/viz@3.31.0" in page
    assert "</script><b>" not in page                 # escaped inside the JSON
    assert "<\\/script><b>x<\\/b>" in page
    assert "--card:#ffffff" in page                    # light theme colors
    assert "--card:#1f2329" in graph_html(gs, None)    # dark by default
    assert "digraph pipeline" in page
