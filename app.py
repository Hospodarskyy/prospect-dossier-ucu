"""Streamlit demo of the Prospect Dossier agent.

- Past runs (free): pick a saved run, see its path through the agent graph,
  replay it step by step, read the dossier, the research iterations, the
  judge's verdicts and the raw result.json / trace.json.
- New run (paid, about $0.10-0.13): send a request and watch the graph live.

Saved runs come from data/storage/outbox (your runs, including adk web and
the service), demo-data/runs (sample runs shipped with the project) and
eval/runs (the runs the evaluation is computed on).

    python -m streamlit run app.py    (the venv's Python: it has google-adk)
"""
import asyncio
import json
import os
import pathlib
import time
import uuid
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent
# before the agent is imported: MODEL and the limits are read at import time
load_dotenv(ROOT / "dossier_agent" / ".env")

from demo_app.component import HEIGHT, graph_html  # noqa: E402
from demo_app.graph import (  # noqa: E402
    INIT_TEXT, NODES, GraphState, Step, final_state, replay_states, steps_from_event,
    steps_from_run,
)
from demo_app.runs import RunInfo, list_runs, load_run  # noqa: E402
from dossier_agent.limits import Limits  # noqa: E402
from dossier_agent.outbox import judge_status  # noqa: E402
from dossier_agent.pricing import use_vertex  # noqa: E402
from dossier_agent.storage import get_storage  # noqa: E402
from service.runner import run_agent  # noqa: E402

DEMO_RUNS = ROOT / "demo-data" / "runs"
EVAL_RUNS = ROOT / "eval" / "runs"
SOURCE_LABEL = {"local": "local run", "demo": "sample run", "eval": "eval run"}
STATUS_COLOR = {"ok": "green", "pass": "green", "partial": "orange",
                "failed": "red", "fail": "red"}
REPLAY_DELAY = 0.8          # seconds per step


def md(text: str) -> str:
    """Streamlit reads $...$ as LaTeX; dossiers mention prices."""
    return str(text).replace("$", "\\$")


def run_sources() -> list[tuple[str, pathlib.Path]]:
    return [("local", get_storage().root / "outbox"), ("demo", DEMO_RUNS), ("eval", EVAL_RUNS)]


def step_line(step: Step, iteration: int) -> str:
    title = NODES[step.node][0]
    prefix = f"iteration {iteration} · " if step.node in (
        "researcher", "source_verifier", "judge", "escalation_checker") and iteration else ""
    return f"{prefix}**{title}**: {md(step.text)}"


def draw(placeholder, state: GraphState) -> None:
    """The agent graph; the mouse over a node shows its state values."""
    theme = getattr(st.context.theme, "type", None)
    with placeholder:
        st.iframe(graph_html(state, theme), height=HEIGHT)


def badge(status: str) -> None:
    st.badge(status, color=STATUS_COLOR.get(status, "gray"))


# --------------------------------------------------------------------------
# One saved run
# --------------------------------------------------------------------------
def show_metrics(result: dict, iterations: int | None) -> None:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}

    def value(key, fmt):
        v = usage.get(key)
        return fmt(v) if isinstance(v, (int, float)) else "—"

    cols = st.columns(5)
    cols[0].metric("Model calls", value("llm_calls", str))
    cols[1].metric("Google searches", value("searches", str))
    cols[2].metric("Cost", value("cost_usd", lambda v: f"${v:.3f}"))
    cols[3].metric("Time", value("elapsed_seconds", lambda v: f"{v:.0f} s"))
    cols[4].metric("Research iterations", iterations if iterations is not None else "—")


def show_graph(steps: list[Step], key: str) -> None:
    replay = st.button("▶ Replay the run", key=f"replay-{key}",
                       help="Animates the saved run step by step. No model calls.")
    graph, caption = st.empty(), st.empty()
    if replay:
        states = replay_states(steps)
        for state, step in zip(states, steps + [None]):
            draw(graph, state)
            caption.markdown(step_line(step, state.iteration) if step else "**Run finished.**")
            time.sleep(REPLAY_DELAY)
    else:
        draw(graph, final_state(steps))
    with st.expander("Steps of this run"):
        iteration = 0
        for step in steps:
            if step.node == "researcher":
                iteration = step.iteration or iteration + 1
            st.markdown(f"- {step_line(step, iteration)}")


def show_feedback(feedback) -> None:
    if not isinstance(feedback, dict):
        st.caption("The judge gave no readable verdict in this iteration.")
        return
    badge(judge_status(feedback))
    if feedback.get("summary"):
        st.markdown(md(feedback["summary"]))
    for key, title in (("missing_sections", "Missing sections"),
                       ("unsourced_claims", "Unsourced claims"),
                       ("stale_news", "Stale news")):
        items = feedback.get(key) or []
        if items:
            st.markdown(f"**{title}**")
            st.markdown("\n".join(f"- {md(i)}" for i in items))


def show_iterations(trace: dict | None) -> None:
    iterations = (trace or {}).get("iterations") or []
    if not iterations:
        st.info("This run has no trace.json (runs before 2026-11-11 did not save one).")
        return
    tabs = st.tabs([f"Iteration {it.get('iteration') or i}" for i, it in enumerate(iterations, 1)])
    for tab, it in zip(tabs, iterations):
        with tab:
            left, right = st.columns([1, 2])
            with left:
                st.markdown("**Judge verdict**")
                show_feedback(it.get("judge_feedback"))
            with right:
                st.markdown("**SourceVerifier** (every quote checked on its page)")
                counts = it.get("verification_counts")
                if isinstance(counts, dict):
                    cols = st.columns(max(len(counts), 1))
                    for col, (k, v) in zip(cols, counts.items()):
                        col.metric(k.replace("_", " "), v)
                facts = it.get("facts") or []
                if facts:
                    st.dataframe(
                        [{"section": f.get("section"), "claim": f.get("claim"),
                          "status": f.get("status"), "weak support": bool(f.get("weak_support")),
                          "source": f.get("final_url") or f.get("url"),
                          "detail": f.get("detail") or ""} for f in facts],
                        hide_index=True,
                        column_config={"source": st.column_config.LinkColumn("source")},
                    )
            with st.expander("Research text (researcher output)"):
                st.code(it.get("research") or "", language=None, wrap_lines=True)
            with st.expander("Verification report (what the judge saw)"):
                st.code(it.get("verification_report") or "", language=None, wrap_lines=True)


def show_run(info: RunInfo) -> None:
    run = load_run(info.path)
    result = run["result"] or {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    trace_iterations = (run["trace"] or {}).get("iterations")
    iterations = data.get("iterations") if isinstance(data.get("iterations"), int) \
        else (len(trace_iterations) if trace_iterations else None)

    st.header(info.company or info.domain or info.run_id)
    badge(info.status)
    details = [info.domain, info.started_at.replace("T", " "), f"run {info.run_id[:8]}",
               SOURCE_LABEL.get(info.source, info.source)]
    if data.get("previous_dossier_date"):
        details.append(f"previous dossier: {data['previous_dossier_date']}")
    st.caption(" · ".join(d for d in details if d))
    show_metrics(result, iterations)

    st.subheader("Agent graph")
    st.caption("Hover over a node to see its state values.")
    show_graph(steps_from_run(result, run["trace"], run["report"]), info.run_id)

    tabs = st.tabs(["Dossier", "Research iterations", "result.json", "trace.json"])
    with tabs[0]:
        for item in result.get("pending_human") or []:
            st.warning(md(f"To check by hand: {item.get('question', item)}"))
        for err in result.get("errors") or []:
            st.error(md(err.get("message", err) if isinstance(err, dict) else err))
        if run["report"]:
            st.markdown(md(run["report"]))
        else:
            st.info("No dossier was written in this run.")
    with tabs[1]:
        show_iterations(run["trace"])
    with tabs[2]:
        st.json(result, expanded=2)
    with tabs[3]:
        if run["trace"]:
            st.json(run["trace"], expanded=1)
        else:
            st.info("No trace.json for this run.")


def past_runs_page() -> None:
    runs = list_runs(run_sources())
    if not runs:
        st.info("No saved runs yet. Start one in **New run**, or copy sample runs "
                "into demo-data/runs.")
        return
    by_path = {str(r.path): r for r in runs}
    if st.session_state.get("run_select") not in by_path:
        st.session_state.pop("run_select", None)
    with st.sidebar:
        selected = st.selectbox("Saved run", list(by_path), key="run_select",
                                format_func=lambda p: by_path[p].label())
    show_run(by_path[selected])


# --------------------------------------------------------------------------
# A new (paid) run
# --------------------------------------------------------------------------
def run_live(request: dict) -> None:
    limits = Limits.from_env()
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.monotonic()

    st.subheader("Agent graph (live)")
    graph = st.empty()
    log = st.status("Running the agent…", expanded=True)
    gs, last_line = GraphState(), [None]

    def show(step: Step) -> None:
        gs.apply(step)
        draw(graph, gs)
        line = step_line(step, gs.iteration)
        if step.text and line != last_line[0]:
            log.markdown(f"`{time.monotonic() - started:5.0f} s` {line}")
            last_line[0] = line

    def on_event(event) -> None:
        for step in steps_from_event(event):
            show(step)

    show(Step("init_state", INIT_TEXT))
    outcome = asyncio.run(run_agent(
        json.dumps(request), run_id=run_id, started_at=started_at, trigger="manual",
        timeout_seconds=limits.seconds + 60, max_llm_calls=limits.max_llm_calls,
        on_event=on_event))

    state = outcome.state
    result = state.get("result") if isinstance(state.get("result"), dict) else None
    if state.get("input_error"):
        log.update(label=f"Invalid request: {state['input_error']}", state="error")
        return
    if result is None:
        log.update(label=f"The run failed: {outcome.error or 'no result'}", state="error")
        return
    status = result["status"]
    show(Step("finalize", f"status: {status}", outcome=status))
    gs.finish()
    draw(graph, gs)
    cost = (result.get("usage") or {}).get("cost_usd")
    label = f"Finished: {status}" + (f" · ${cost:.3f}" if isinstance(cost, (int, float)) else "")
    log.update(label=label, state="error" if status == "failed" else "complete", expanded=False)
    if outcome.error:
        st.warning(md(outcome.error))

    prefix = state.get("outbox_prefix")
    if prefix:
        path = str(get_storage().root / prefix)
        st.success("Saved. The run is now in **Past runs**, with the dossier and the trace.")
        st.button("Open this run", type="primary",
                  on_click=lambda: st.session_state.update(goto=path))


def new_run_page() -> None:
    st.header("New dossier")
    has_key = bool(os.getenv("GOOGLE_API_KEY")) or use_vertex()
    if not has_key:
        st.warning("Set GOOGLE_API_KEY in dossier_agent/.env to run the agent. "
                   "Past runs work without a key.")
    with st.form("request"):
        company = st.text_input("Company", placeholder="Plausible Analytics")
        domain = st.text_input("Domain", placeholder="plausible.io")
        context = st.text_area("Context (optional)",
                               placeholder="What you already know or want to find out")
        submitted = st.form_submit_button("Generate dossier", type="primary",
                                          disabled=not has_key)
    st.caption("Paid: one dossier takes 2–4 minutes and costs about $0.10–0.13. "
               "A repeated request for the same domain fills “What changed”.")
    if submitted:
        request = {"company": company.strip(), "domain": domain.strip()}
        if context.strip():
            request["context"] = context.strip()
        run_live(request)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
st.set_page_config(page_title="Prospect Dossier", page_icon="🗂️", layout="wide")

if "goto" in st.session_state:          # "Open this run" after a new run
    st.session_state["mode"] = "Past runs"
    st.session_state["run_select"] = st.session_state.pop("goto")

with st.sidebar:
    st.title("Prospect Dossier")
    st.caption("Multi-agent pipeline on Google ADK + Gemini. "
               "Seller: Metacortex (fictional, test data).")
    mode = st.radio("Mode", ["Past runs", "New run"], key="mode",
                    captions=["free: replay saved runs", "paid: runs the agent"])

if mode == "Past runs":
    past_runs_page()
else:
    new_run_page()
