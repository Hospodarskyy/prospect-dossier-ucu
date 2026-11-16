"""The agent graph of the Streamlit demo: steps of a run and their Graphviz picture.

Two sources of steps, one picture:
- a saved run: steps_from_run(result, trace, report), rebuilt from trace.json;
- a live run: steps_from_event(event), one ADK event at a time.
GraphState.apply(step) moves the highlight and collects the state values shown
when the mouse is over a node; graph_dot(state) draws the graph.
"""
import re
from dataclasses import dataclass, field

from dossier_agent.outbox import judge_status, parse_feedback

MAX_ITERATIONS = 3

# node id -> (title, kind shown under the title)
NODES = {
    "init_state": ("init_state", "script"),
    "researcher": ("researcher", "LLM"),
    "source_verifier": ("SourceVerifier", "script, no LLM"),
    "judge": ("judge", "LLM"),
    "escalation_checker": ("EscalationChecker", "script"),
    "writer": ("writer", "LLM"),
    "finalize": ("finalize_run", "script"),
}
LOOP = ("researcher", "source_verifier", "judge", "escalation_checker")
# tool node -> the agent that uses it
TOOLS = {
    "google_search": "researcher",
    "load_seller_cases": "writer",
    "check_dossier_format": "writer",
}

# colors that read on both the light and the dark Streamlit theme
COLORS = {
    "todo": ("#eef0f3", "#b9bec6", "#5b626c"),       # fill, border, text
    "done": ("#d7e6f7", "#4a78b0", "#1d2b3a"),
    "active": ("#ffd479", "#b47b00", "#2b2100"),
}
OUTCOME_BORDER = {"pass": "#2e8b57", "ok": "#2e8b57",
                  "fail": "#c0392b", "failed": "#c0392b", "partial": "#d98200"}
LINE = "#8a929c"
INIT_TEXT = "request parsed; seller file and previous dossier loaded"

Info = tuple[tuple[str, str], ...]      # (key, value) rows of a hover card


@dataclass(frozen=True)
class Step:
    node: str                    # a key of NODES
    text: str                    # one line for the log
    iteration: int | None = None
    outcome: str = ""            # judge: pass | fail; finalize: ok | partial | failed
    tool: str = ""               # a key of TOOLS, when the step is a tool call
    info: Info = ()              # state values for the node's hover card
    tool_info: Info = ()         # state values for the tool's hover card


@dataclass
class GraphState:
    done: set = field(default_factory=set)
    active: str | None = None
    active_tool: str | None = None
    iteration: int = 0
    verdicts: list = field(default_factory=list)     # judge verdict per iteration
    status: str = ""                                 # final status of the run
    info: dict = field(default_factory=dict)         # node id -> {key: value}

    def apply(self, step: Step) -> None:
        if step.node != self.active:
            self._close_active()
            if step.node == "researcher":            # a new loop iteration
                self.iteration = step.iteration or self.iteration + 1
                self.done -= set(LOOP)
                for node in (*LOOP, "google_search"):  # the cards show this iteration only
                    self.info.pop(node, None)
                self._add("researcher", (("iteration", str(self.iteration)),))
            self.active = step.node
        if step.tool != self.active_tool:
            if self.active_tool:
                self.done.add(self.active_tool)
            self.active_tool = step.tool or None
        self._add(step.node, step.info)
        if step.tool:
            self._add(step.tool, step.tool_info)
        if step.node == "judge" and step.outcome in ("pass", "fail"):
            self.verdicts = self.verdicts[: max(self.iteration - 1, 0)] + [step.outcome]
        if step.node == "finalize" and step.outcome:
            self.status = step.outcome

    def finish(self) -> None:
        """The run is over: nothing is active any more."""
        self._close_active()
        self.active = None

    def _add(self, node: str, rows: Info) -> None:
        if rows:
            self.info[node] = {**self.info.get(node, {}), **dict(rows)}

    def _close_active(self) -> None:
        if self.active:
            self.done.add(self.active)
        if self.active_tool:
            self.done.add(self.active_tool)
        self.active_tool = None


def replay_states(steps: list[Step]) -> list[GraphState]:
    """A snapshot after every step, and the finished state at the end."""
    state, states = GraphState(), []
    for step in steps:
        state.apply(step)
        states.append(_copy(state))
    state.finish()
    states.append(_copy(state))
    return states


def final_state(steps: list[Step]) -> GraphState:
    return replay_states(steps)[-1]


def _copy(state: GraphState) -> GraphState:
    return GraphState(done=set(state.done), active=state.active, active_tool=state.active_tool,
                      iteration=state.iteration, verdicts=list(state.verdicts),
                      status=state.status, info={k: dict(v) for k, v in state.info.items()})


# --------------------------------------------------------------------------
# Step texts and hover-card values
# --------------------------------------------------------------------------
COUNT_ORDER = ("supported", "weak_support", "hypothesis", "pending")


def short(value, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rows(**values) -> Info:
    """Hover-card rows; None and "" are left out. Keys: _ becomes a space."""
    return tuple((k.replace("_", " "), short(v)) for k, v in values.items()
                 if v is not None and v != "")


def _searches_reported(research: str) -> str | None:
    match = re.search(r"Searches performed:\s*(\d+)", research or "")
    return match.group(1) if match else None


def _sourced_facts(research: str) -> list[str]:
    return [line.strip()[2:] for line in (research or "").splitlines()
            if line.lstrip().startswith("- ") and "(source:" in line]


def research_text(research: str) -> str:
    searches = _searches_reported(research)
    # the researcher's own count; the "Google searches" metric comes from grounding data
    prefix = f"reports {searches} searches, " if searches else ""
    return f"{prefix}{len(_sourced_facts(research))} facts with a source"


def research_info(research: str) -> Info:
    facts = _sourced_facts(research)
    first = facts[0].split(" (source:")[0] if facts else None
    return _rows(searches_reported=_searches_reported(research),
                 facts_with_a_source=len(facts), first_fact=first)


def counts_text(counts) -> str:
    if not isinstance(counts, dict):
        return "verification failed (see the report)"
    keys = [k for k in COUNT_ORDER if k in counts] + sorted(k for k in counts if k not in COUNT_ORDER)
    return " · ".join(f"{k} {counts[k]}" for k in keys) or "nothing to verify"


def verifier_info(counts, facts) -> Info:
    rows = list(_rows(verification=counts_text(counts)))
    facts = [f for f in facts or [] if isinstance(f, dict)]
    if facts:
        rows += _rows(facts_checked=len(facts),
                      weak_support=sum(1 for f in facts if f.get("weak_support")),
                      blocked_pages=sum(1 for f in facts if f.get("blocked")),
                      fetch_errors=sum(1 for f in facts if f.get("fetch_error")))
    return tuple(rows)


def judge_text(feedback) -> tuple[str, str]:
    status = judge_status(feedback)
    summary = parse_feedback(feedback).get("summary", "")
    return f"verdict: {status}" + (f" ({short(summary, 140)})" if summary else ""), status


def judge_info(feedback) -> Info:
    fb = parse_feedback(feedback)

    def listed(key):
        items = fb.get(key) or []
        return f"{len(items)}: " + "; ".join(map(str, items)) if items else "0"

    return _rows(status=judge_status(feedback), summary=fb.get("summary"),
                 missing_sections=listed("missing_sections"),
                 unsourced_claims=listed("unsourced_claims"), stale_news=listed("stale_news"))


def usage_info(usage) -> Info:
    if not isinstance(usage, dict):
        return ()
    cost = usage.get("cost_usd")
    seconds = usage.get("elapsed_seconds")
    searches = usage.get("searches")
    source = usage.get("searches_source")
    return _rows(model_calls=usage.get("llm_calls"),
                 searches=f"{searches} ({source})" if searches is not None and source else searches,
                 cost=f"${cost:.3f}" if isinstance(cost, (int, float)) else None,
                 time=f"{seconds:.0f} s" if isinstance(seconds, (int, float)) else None,
                 hard_stop=usage.get("hard_stop"), research_stop=usage.get("research_stop"))


def dossier_info(md: str) -> Info:
    md = md or ""
    return _rows(dossier=f"{len(md.split())} words, {md.count('## ')} sections",
                 pending_items=md.count("[Pending]"))


# --------------------------------------------------------------------------
# Steps of a saved run
# --------------------------------------------------------------------------
def steps_from_run(result: dict | None, trace: dict | None, report: str | None) -> list[Step]:
    """The path of a saved run through the graph, from result.json and trace.json.
    Runs without trace.json (older ones) get the loop steps without details."""
    result = result or {}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    status = str(result.get("status") or "unknown")
    steps = [Step("init_state", INIT_TEXT, info=_rows(
        company=data.get("company"), domain=data.get("domain"), seller=data.get("seller"),
        previous_dossier=data.get("previous_dossier_date") or "none (first dossier)",
        trigger=result.get("trigger"), started_at=result.get("started_at"),
        run_id=result.get("run_id")))]

    iterations = (trace or {}).get("iterations") or []
    if iterations:
        for i, it in enumerate(iterations, start=1):
            n = it.get("iteration") or i
            research = it.get("research", "")
            searches = _searches_reported(research)
            steps.append(Step("researcher", research_text(research), n, tool="google_search",
                              info=research_info(research),
                              tool_info=_rows(searches_reported=searches)))
            steps.append(Step("source_verifier", counts_text(it.get("verification_counts")), n,
                              info=verifier_info(it.get("verification_counts"), it.get("facts"))))
            if "judge_feedback" not in it:
                break                   # the run stopped before the judge answered
            text, verdict = judge_text(it.get("judge_feedback"))
            steps.append(Step("judge", text, n, outcome=verdict,
                              info=judge_info(it.get("judge_feedback"))))
            decision = _escalation_text(verdict, i == len(iterations), usage)
            steps.append(Step("escalation_checker", decision, n,
                              info=_rows(iterations=n, decision=decision)))
    else:
        total = data.get("iterations") if isinstance(data.get("iterations"), int) else 0
        last = data.get("judge_status") if data.get("judge_status") in ("pass", "fail") else ""
        for n in range(1, total + 1):
            steps.append(Step("researcher", "no trace saved for this run", n))
            steps.append(Step("source_verifier", "no trace saved for this run", n))
            verdict = last if n == total else "fail"
            steps.append(Step("judge", f"verdict: {verdict or 'unknown'}", n, outcome=verdict,
                              info=_rows(status=verdict or "unknown")))
            decision = _escalation_text(verdict, n == total, usage)
            steps.append(Step("escalation_checker", decision, n,
                              info=_rows(iterations=n, decision=decision)))

    if report is not None:
        cases = data.get("seller_cases") if isinstance(data.get("seller_cases"), list) else []
        if cases:       # the cited case studies can only come from load_seller_cases
            cited = "; ".join(f"{c.get('id')} {c.get('title', '')}".strip()
                              for c in cases if isinstance(c, dict))
            steps.append(Step("writer", f"cites {len(cases)} case studies from load_seller_cases",
                              tool="load_seller_cases", tool_info=_rows(cited_cases=cited)))
        pending = result.get("pending_human") or []
        steps.append(Step("writer", "dossier written", info=dossier_info(report) + _rows(
            cited_cases=len(cases), to_check_by_hand=len(pending))))
    errors = result.get("errors") or []
    message = errors[0].get("message", "") if errors and isinstance(errors[0], dict) else ""
    note = f"; {message}" if message else ""
    steps.append(Step("finalize", f"status: {status}{note}", outcome=status,
                      info=_rows(status=status) + usage_info(usage) + _rows(error=message)))
    return steps


def _escalation_text(verdict: str, is_last: bool, usage: dict) -> str:
    if verdict == "pass":
        return "judge passed: on to the writer"
    if not is_last:
        return "judge failed: next iteration"
    reason = usage.get("research_stop") or usage.get("hard_stop")
    return f"stop: {reason}" if reason else f"stop: judge did not pass ({MAX_ITERATIONS} iterations max)"


# --------------------------------------------------------------------------
# Steps of a live run (ADK events)
# --------------------------------------------------------------------------
def steps_from_event(event) -> list[Step]:
    """Steps for one ADK event; [] for events that change nothing on the graph."""
    author = getattr(event, "author", "") or ""
    actions = getattr(event, "actions", None)
    delta = getattr(actions, "state_delta", None) or {}
    calls = event.get_function_calls() if hasattr(event, "get_function_calls") else []
    so_far = _usage_so_far(delta.get("usage"))

    if author == "dossier_pipeline":         # the callbacks of the root agent
        text = _event_text(event)
        if text:                             # init_state answered: the request was rejected
            return [Step("init_state", text, outcome="failed", info=_rows(error=text))]
        result = delta.get("result")
        if isinstance(result, dict):         # finalize_run saved the result
            status = str(result.get("status") or "unknown")
            return [Step("finalize", f"status: {status}", outcome=status,
                         info=_rows(status=status) + usage_info(result.get("usage"))
                         + _rows(outbox=delta.get("outbox_prefix")))]
        if delta:                            # init_state filled the state
            return [Step("init_state", INIT_TEXT, info=_rows(
                company=delta.get("company"), domain=delta.get("domain"),
                context=delta.get("context"), seller=delta.get("seller"),
                previous_dossier=delta.get("previous_dossier_date") or "none (first dossier)",
                run_id=delta.get("run_id"), started_at=delta.get("started_at")))]
        return []
    if author == "researcher":
        if "research" in delta:
            research = str(delta["research"])
            return [Step("researcher", research_text(research), tool="google_search",
                         info=research_info(research) + so_far,
                         tool_info=_rows(searches_reported=_searches_reported(research)))]
        return [Step("researcher", "searching the web and writing facts", tool="google_search")]
    if author == "source_verifier":
        trace = delta.get("trace") if isinstance(delta.get("trace"), list) else []
        facts = trace[-1].get("facts") if trace and isinstance(trace[-1], dict) else []
        return [Step("source_verifier", counts_text(delta.get("verification_counts")),
                     info=verifier_info(delta.get("verification_counts"), facts))]
    if author == "judge":
        if "judge_feedback" not in delta:
            return [Step("judge", "reading the research and the verification report")]
        feedback = delta["judge_feedback"]
        text, verdict = judge_text(feedback)
        return [Step("judge", text, outcome=verdict, info=judge_info(feedback) + so_far)]
    if author == "escalation_checker":
        stop = bool(getattr(actions, "escalate", None))
        usage = delta.get("usage") if isinstance(delta.get("usage"), dict) else {}
        reason = usage.get("research_stop")
        text = (f"stop: {reason}" if reason else "loop ends: on to the writer") if stop \
            else "judge failed: next iteration"
        return [Step("escalation_checker", text,
                     info=_rows(iterations=delta.get("iterations"), decision=text))]
    if author == "writer":
        named = [c for c in calls if c.name in TOOLS]
        if named:
            return [Step("writer", f"calls {c.name}", tool=c.name, tool_info=_call_args(c))
                    for c in named]
        responses = event.get_function_responses() if hasattr(event, "get_function_responses") else []
        answers = [Step("writer", _tool_answer(r.name, r.response), tool=r.name,
                        tool_info=_rows(answer=_tool_answer(r.name, r.response)))
                   for r in responses if r.name in TOOLS]
        if answers:
            return answers
        if "dossier_md" in delta:
            return [Step("writer", "dossier written",
                         info=dossier_info(str(delta["dossier_md"])) + so_far)]
        return [Step("writer", "")]          # moves the highlight, no log line
    return []


def _usage_so_far(usage) -> Info:
    if not isinstance(usage, dict):
        return ()
    cost = usage.get("cost_usd")
    return _rows(model_calls_so_far=usage.get("llm_calls"),
                 cost_so_far=f"${cost:.3f}" if isinstance(cost, (int, float)) else None)


def _call_args(call) -> Info:
    args = getattr(call, "args", None) or {}
    if call.name == "load_seller_cases":
        tech = args.get("tech")
        return _rows(industry=args.get("industry"),
                     tech=", ".join(map(str, tech)) if isinstance(tech, list) else tech)
    if call.name == "check_dossier_format":
        md = str(args.get("md") or "")
        return _rows(draft=f"{len(md.split())} words")
    return ()


def _tool_answer(name: str, response) -> str:
    response = response if isinstance(response, dict) else {}
    if name == "load_seller_cases":
        cases = response.get("cases") or []
        ids = ", ".join(str(c.get("id")) for c in cases if isinstance(c, dict) and c.get("id"))
        return f"load_seller_cases returned {len(cases)} case studies" + (f" ({ids})" if ids else "")
    if name == "check_dossier_format":
        if response.get("success"):
            return "format check passed"
        return f"format check failed: {short(response.get('message') or '', 160)}"
    return f"{name} answered"


def _event_text(event) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return " ".join(p.text for p in parts if getattr(p, "text", None)).strip()


# --------------------------------------------------------------------------
# Graphviz picture
# --------------------------------------------------------------------------
def _node(node_id: str, title: str, kind: str, state: str, border: str | None,
          shape: str = "box") -> str:
    fill, line, text = COLORS[state]
    width = "2.6" if state == "active" or border else "1.2"
    label = f'<<b>{title}</b><br/><font point-size="11">{kind}</font>>'
    return (f'  {node_id} [label={label}, shape={shape}, style="rounded,filled", '
            f'fillcolor="{fill}", color="{border or line}", fontcolor="{text}", penwidth={width}];')


def state_of(node_id: str, gs: GraphState) -> str:
    """"active", "done" or "todo"."""
    if node_id in (gs.active, gs.active_tool):
        return "active"
    return "done" if node_id in gs.done else "todo"


def node_title(node_id: str) -> tuple[str, str]:
    return (node_id, "tool") if node_id in TOOLS else NODES[node_id]


def graph_dot(gs: GraphState) -> str:
    """DOT text of the pipeline with the current highlight. Left to right; each
    tool sits right under the agent that uses it."""
    lines = [
        "digraph pipeline {",
        '  graph [rankdir=LR, bgcolor="transparent", fontname="Helvetica", nodesep=0.3, ranksep=0.4];',
        '  node [fontname="Helvetica", fontsize=15, margin="0.16,0.07"];',
        f'  edge [color="{LINE}", fontcolor="{LINE}", fontname="Helvetica", fontsize=12, arrowsize=0.8];',
    ]
    border = {}
    if gs.verdicts:
        border["judge"] = OUTCOME_BORDER.get(gs.verdicts[-1])
    if gs.status:
        border["finalize"] = OUTCOME_BORDER.get(gs.status)
    verdicts = " ".join(f"{i}:{v}" for i, v in enumerate(gs.verdicts, start=1))

    def node(node_id: str, shape: str = "box") -> str:
        title, kind = node_title(node_id)
        if node_id == "judge" and verdicts:
            kind = f"LLM · {verdicts}"
        return _node(node_id, title, kind, state_of(node_id, gs), border.get(node_id), shape)

    iteration = f"iteration {gs.iteration} of max {MAX_ITERATIONS}" if gs.iteration \
        else f"up to {MAX_ITERATIONS} iterations"
    lines += [
        node("init_state"),
        "  subgraph cluster_loop {",
        f'    label="research loop · {iteration}"; labeljust=l; fontsize=13;',
        f'    style="rounded,dashed"; color="{LINE}"; fontcolor="{LINE}";',
        *("  " + node(n) for n in LOOP),
        "  " + node("google_search", "ellipse"),
        "    { rank=same; researcher; google_search; }",
        "  }",
        node("writer"),
        node("load_seller_cases", "ellipse"),
        node("check_dossier_format", "ellipse"),
        "  { rank=same; writer; load_seller_cases; check_dossier_format; }",
        node("finalize"),
    ]
    lines += [f"  {owner} -> {tool} [style=dotted, arrowhead=none];" for tool, owner in TOOLS.items()]
    lines += [
        "  init_state -> researcher;",
        "  researcher -> source_verifier -> judge -> escalation_checker;",
        '  escalation_checker -> researcher [label="fail", style=dashed, constraint=false];',
        '  escalation_checker -> writer [label="pass / limit"];',
        "  writer -> finalize;",
        "}",
    ]
    return "\n".join(lines)
