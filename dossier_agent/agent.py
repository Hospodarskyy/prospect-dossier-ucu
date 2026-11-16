import json
import os
import pathlib
import uuid
from datetime import date, datetime, timezone
from typing import AsyncGenerator

from dotenv import load_dotenv
from google.adk.agents import BaseAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import Agent
from google.adk.events import Event, EventActions
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import google_search
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .seller_cases import angle_section, load_cases_file, select_candidates
from .format_check import check_dossier
from .limits import (
    Limits, add_response, describe, elapsed_seconds, hard_stop_reason, new_usage,
    research_stop_reason,
)
from .instructions import (
    JUDGE_INSTRUCTION,
    RESEARCHER_INSTRUCTION,
    WRITER_INSTRUCTION,
)
from .memory import (
    build_record, format_news_since, format_prior_knowledge, load_previous_dossier, news_since,
    save_dossier,
)
from .outbox import (
    AGENT_NAME,
    add_sources, build_data, build_pending_human, build_result, check_run_id, judge_status,
    replace_urls,
    outbox_prefix, write_outbox,
)
from .request import format_request, parse_request
from .schemas import JudgeFeedback
from .verification import format_verification, resolved_urls, verify_research

load_dotenv()
MODEL = os.getenv("MODEL", "gemini-3.8-flash")
WRITER_MODEL = os.getenv("WRITER_MODEL") or MODEL 
TRIGGERS = ("inbox", "manual")
THINKING_LEVELS = ("minimal", "low", "medium", "high")

LIMITS = Limits.from_env()

ROOT_DIR = pathlib.Path(__file__).parent.parent
CACHE_DIR = ROOT_DIR / "data" / "cache" / "pages"
RUNS_DIR = ROOT_DIR / "data" / "runs"


def thinking_config(env_name: str, default: str = "") -> types.ThinkingConfig | None:
    """Thinking level from an env variable (minimal | low | medium | high).
    Unset: `default`. Set but empty: the model default (None)."""
    level = os.getenv(env_name, default).strip().lower()
    if not level:
        return None
    if level not in THINKING_LEVELS:
        raise ValueError(f"{env_name} must be one of {THINKING_LEVELS}, got {level!r}")
    return types.ThinkingConfig(thinking_level=level)


def retry_options() -> types.HttpRetryOptions:
    """Retries of one model request on 408/429/5xx (rate limits of a free API
    key, a busy model), with a growing pause of 2 s up to 30 s.
    MODEL_ATTEMPTS counts the first request too; 1 = no retries."""
    attempts = int(os.getenv("MODEL_ATTEMPTS", "4"))
    if attempts < 1:
        raise ValueError(f"MODEL_ATTEMPTS must be at least 1, got {attempts}")
    return types.HttpRetryOptions(attempts=attempts, initial_delay=2.0, max_delay=30.0)


def gemini(model: str) -> Gemini:
    """The model of an LLM agent. Gemini API key or Vertex AI is chosen by
    google-genai from the environment (GOOGLE_API_KEY / GOOGLE_GENAI_USE_VERTEXAI)."""
    return Gemini(model=model, retry_options=retry_options())


def model_config(thinking_env: str = "", thinking_default: str = "") -> types.GenerateContentConfig:
    """generate_content_config for an LLM agent: an optional thinking level."""
    thinking = thinking_config(thinking_env, thinking_default) if thinking_env else None
    return types.GenerateContentConfig(thinking_config=thinking)


# --------------------------------------------------------------------------
# State set up before the pipeline runs (no LLM)
# --------------------------------------------------------------------------
def init_state(callback_context: CallbackContext) -> types.Content | None:
    """Parse the JSON request into state. On invalid input, return a message:
    ADK then ends the invocation and no LLM agent runs. A missing or invalid
    config/seller_cases.md raises ConfigError: the run fails before any model call."""
    state = callback_context.state
    state["today"] = date.today().isoformat()
    if "request" not in state:     # one session = one request
        content = callback_context.user_content
        text = "".join(p.text or "" for p in content.parts) if content and content.parts else ""
        try:
            req = parse_request(text)
        except ValueError as exc:
            state["input_error"] = str(exc)
            return types.Content(
                role="model", parts=[types.Part(text=f"Invalid request: {exc}")]
            )
        state["input_error"] = ""      # clear an error from an earlier attempt
        for key, value in req.items():
            state[key] = value
        state["request"] = format_request(req)
        if not state.get("run_id"):    # the service sets run_id; adk web does not
            state["run_id"] = new_run_id()
        try:
            check_run_id(state["run_id"])
        except ValueError as exc:
            state["input_error"] = str(exc)
            return types.Content(
                role="model", parts=[types.Part(text=f"Invalid request: {exc}")]
            )
        if not state.get("started_at"):
            state["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["trigger"] = state.get("trigger") or "manual"
        if state["trigger"] not in TRIGGERS:
            state["input_error"] = f"invalid trigger: {state['trigger']!r}"
            return types.Content(
                role="model", parts=[types.Part(text=f"Invalid request: {state['input_error']}")]
            )
        state["iterations"] = 0
        state["usage"] = new_usage()
        seller, cases = load_cases_file()         # raises ConfigError
        state["seller"] = seller
        state["angle_section"] = angle_section(seller)
        state["seller_cases"] = cases
        state["loaded_cases"] = []                # filled by the load_seller_cases tool
        state["case_study_urls"] = []
        previous = load_previous_dossier(req["domain"])
        state["prior_knowledge"] = format_prior_knowledge(previous)
        state["previous_dossier_date"] = previous["saved_at"][:10] if previous else ""
    return None


def new_run_id() -> str:
    return str(uuid.uuid4())


def _loaded_cases(state) -> list[dict]:
    cases = state.get("loaded_cases") or []
    return [c for c in cases if isinstance(c, dict) and c.get("url")]


def _final_usage(state) -> dict:
    usage = dict(state.get("usage") or new_usage())
    usage["elapsed_seconds"] = round(elapsed_seconds(state.get("started_at")), 1)
    return usage


def _blocked_urls(state) -> list[str]:
    """Source pages of the last iteration that sent a bot-protection page."""
    trace = state.get("trace") or []
    facts = trace[-1].get("facts", []) if trace else []
    urls = [f.get("final_url") or f.get("url") for f in facts if f.get("blocked")]
    return list(dict.fromkeys(u for u in urls if u))


def _blocked_note(urls: list[str]) -> list[dict]:
    if not urls:
        return []
    return [{"id": "blocked-pages",
             "question": f"{len(urls)} source page(s) sent a bot-protection page and could not "
                         "be checked: " + ", ".join(urls[:3]),
             "source_ref": urls[0]}]


def _trace_json(state) -> str:
    return json.dumps({"run_id": state.get("run_id"), "iterations": state.get("trace") or []},
                      indent=2, ensure_ascii=False, default=str)


def _stop_notes(usage: dict) -> tuple[list[dict], list[dict]]:
    """errors and pending_human entries for a hard stop or an early research stop."""
    errors, pending = [], []
    if usage.get("hard_stop"):
        text = describe(usage["hard_stop"], LIMITS)
        errors.append({"source": "hard_stop", "message": text})
        pending.append({"id": "hard-stop", "question": f"Run stopped: {text}. "
                        "The dossier may be incomplete.", "source_ref": "usage"})
    if usage.get("research_stop"):
        text = describe(usage["research_stop"], LIMITS)
        pending.append({"id": "research-stopped", "question": f"Research ended early: {text}.",
                        "source_ref": "usage"})
    return errors, pending


def finalize_run(callback_context: CallbackContext) -> None:
    """After the pipeline (no LLM): save memory and write the outbox.

    Runs only when the pipeline finished normally. If no dossier was written,
    nothing is saved: memory keeps the previous dossier, and the service
    records the run as failed.
    """
    state = callback_context.state
    dossier_md = state.get("dossier_md")
    domain = state.get("domain")
    usage = _final_usage(state)
    blocked = _blocked_urls(state)
    usage["blocked_pages"] = len(blocked)
    stop_errors, stop_pending = _stop_notes(usage)
    stop_pending += _blocked_note(blocked)
    if not domain or not isinstance(dossier_md, str) or not dossier_md.strip():
        if domain and usage["hard_stop"]:
            # stopped before any dossier was written: report it, keep memory as is
            result = build_result(
                agent=AGENT_NAME, run_id=state["run_id"], trigger=state.get("trigger", "manual"),
                started_at=state["started_at"], status="failed", pending_human=stop_pending,
                errors=stop_errors, usage=usage, data=None)
            prefix = outbox_prefix(state["started_at"], state["run_id"])
            write_outbox(prefix, None, result, extra_files={"trace.json": _trace_json(state)})
            state["outbox_prefix"] = prefix
            state["result"] = result
        return None

    feedback = state.get("judge_feedback")
    status_of_judge = judge_status(feedback)
    errors = list(stop_errors)
    check = check_dossier(dossier_md, str(state.get("research", "")),
                          set(state.get("case_study_urls", [])),
                          angle_section=state["angle_section"])
    if not check["success"]:
        errors.append({"source": "format_check", "message": check["message"]})

    output_md = replace_urls(dossier_md, state.get("resolved_urls"))

    # memory first: it is what the next run depends on
    state["saved_dossier_key"] = save_dossier(domain, build_record(
        domain=domain, run_id=state["run_id"], judge_status=status_of_judge,
        dossier_md=output_md,
    ))

    result = build_result(
        agent=AGENT_NAME,
        run_id=state["run_id"],
        trigger=state.get("trigger", "manual"),
        started_at=state["started_at"],
        status="ok" if status_of_judge == "pass" and not errors else "partial",
        pending_human=stop_pending + build_pending_human(feedback, output_md),
        errors=errors,
        usage=usage,
        data=build_data(
            company=state.get("company", ""),
            domain=domain,
            iterations=state.get("iterations", 0),
            judge_feedback=feedback,
            dossier_md=output_md,
            verification_counts=state.get("verification_counts"),
            case_studies=_loaded_cases(state),
            seller=state["seller"],
            previous_dossier_date=state.get("previous_dossier_date"),
        ),
    )
    prefix = outbox_prefix(state["started_at"], state["run_id"])
    write_outbox(prefix, add_sources(output_md), result,
                 extra_files={"trace.json": _trace_json(state)})
    state["outbox_prefix"] = prefix
    state["result"] = result
    return None


# --------------------------------------------------------------------------
# Tools for the writer (no LLM)
# --------------------------------------------------------------------------
def load_seller_cases(industry: str, tech: list[str], tool_context: ToolContext) -> dict:
    """Return up to 5 of the seller's case studies to choose from, most likely
    matches first.

    Args:
      industry: the company's industry, e.g. "SaaS", "E-commerce".
      tech: technologies and pain keywords from RESEARCH, e.g.
        ["ClickHouse", "Hetzner", "vertical scaling"].

    Returns {"success": True, "cases": [{id, title, industry, technologies,
    problem, result, url}, ...]}. Only these cases may be cited in the
    angle section.
    """
    candidates = select_candidates(tool_context.state.get("seller_cases") or [], industry, tech)
    loaded = list(tool_context.state.get("loaded_cases") or [])
    known = {c["url"] for c in loaded}
    loaded += [c for c in candidates if c["url"] not in known]
    tool_context.state["loaded_cases"] = loaded
    tool_context.state["case_study_urls"] = [c["url"] for c in loaded]
    return {"success": True, "cases": candidates}


def check_dossier_format(md: str, tool_context: ToolContext) -> dict:
    """Check the dossier format and length, and that every URL comes from
    RESEARCH (facts) or returned by load_seller_cases (angle section).
    Returns {"success": bool, "message": str}."""
    tool_context.state["dossier_draft"] = md   # used if a hard stop ends the writer
    return check_dossier(
        md,
        research=str(tool_context.state.get("research", "")),
        case_study_urls=set(tool_context.state.get("case_study_urls", [])),
        angle_section=tool_context.state.get("angle_section", ""),
    )


def prepare_writer(callback_context: CallbackContext) -> None:
    """Before the writer (no LLM): which news is newer than the previous
    dossier. Computed from the final research, so the writer does not have to
    compare dates itself."""
    state = callback_context.state
    since = state.get("previous_dossier_date") or ""
    news = news_since(str(state.get("research") or ""), since)
    state["new_news"] = format_news_since(news, since)
    return None


# --------------------------------------------------------------------------
# Hard stops: model callbacks on every LLM agent (no LLM)
# --------------------------------------------------------------------------
def _blocked_response(agent: str, state, reason: str) -> LlmResponse:
    """What a blocked agent 'answers' instead of calling the model. It must be
    valid for that agent: the judge has an output_schema, the others write
    text into their output_key."""
    if agent == "judge":
        previous = state.get("judge_feedback")
        text = json.dumps(previous) if isinstance(previous, dict) else json.dumps({
            "status": "fail", "missing_sections": [], "unsourced_claims": [], "stale_news": [],
            "summary": f"Not reviewed: {describe(reason, LIMITS)}."})
    elif agent == "researcher":
        text = str(state.get("research") or "- [Pending] no data found")
    else:   # writer: the last draft it checked, or nothing
        text = str(state.get("dossier_draft") or "")
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def limit_before_model(callback_context: CallbackContext,
                       llm_request: LlmRequest) -> LlmResponse | None:
    """Block the call if a hard limit is reached, or if the research loop was
    stopped and this is a research-loop agent. Otherwise count the call."""
    state = callback_context.state
    agent = callback_context.agent_name
    usage = dict(state.get("usage") or new_usage())
    reason = hard_stop_reason(usage, LIMITS, elapsed_seconds(state.get("started_at")))
    if reason:
        usage["hard_stop"] = usage["hard_stop"] or reason
        state["usage"] = usage
        return _blocked_response(agent, state, reason)
    if agent in ("researcher", "judge") and usage["research_stop"]:
        return _blocked_response(agent, state, usage["research_stop"])
    usage["llm_calls"] += 1
    state["usage"] = usage
    return None


def limit_after_model(callback_context: CallbackContext,
                      llm_response: LlmResponse) -> LlmResponse | None:
    """Add tokens, cost and searches of a real model response to state["usage"]."""
    if llm_response.partial:
        return None
    um = llm_response.usage_metadata
    grounding = llm_response.grounding_metadata
    queries = grounding.web_search_queries if grounding is not None else None
    text = "".join(p.text or "" for p in (llm_response.content.parts or [])
                   if not p.thought) if llm_response.content else ""
    callback_context.state["usage"] = add_response(
        callback_context.state.get("usage") or new_usage(),
        model=llm_response.model_version or MODEL,
        input_tokens=(um.prompt_token_count or 0) if um else 0,
        output_tokens=(um.candidates_token_count or 0) if um else 0,
        thinking_tokens=(um.thoughts_token_count or 0) if um else 0,
        grounding_queries=list(queries) if queries is not None else None,
        response_text=text,
        is_researcher=callback_context.agent_name == "researcher",
    )
    return None


# --------------------------------------------------------------------------
# Non-LLM agents
# --------------------------------------------------------------------------
TRACE_FACT_FIELDS = ("section", "claim", "url", "final_url", "status", "weak_support",
                     "detail", "date", "date_check", "http_status", "fetch_error",
                     "page_head", "blocked")


class EscalationChecker(BaseAgent):
    name: str = "escalation_checker"
    description: str = ("Counts iterations; stops the research loop when the judge says "
                        "'pass' or a limit is reached.")

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        delta = {"iterations": int(state.get("iterations") or 0) + 1}
        is_pass = judge_status(state.get("judge_feedback")) == "pass"
        trace = list(state.get("trace") or [])
        if trace:   # the judge's answer for this iteration
            trace[-1] = {**trace[-1], "judge_feedback": state.get("judge_feedback")}
            delta["trace"] = trace
        usage = dict(state.get("usage") or new_usage())
        stop = bool(usage["hard_stop"] or usage["research_stop"])
        if not is_pass and not stop:
            reason = research_stop_reason(usage, LIMITS)
            if reason:      # no new iteration: keep the rest for the writer
                usage["research_stop"] = reason
                delta["usage"] = usage
                stop = True
        yield Event(invocation_id=ctx.invocation_id, author=self.name,
                    actions=EventActions(escalate=(is_pass or stop) or None, state_delta=delta))


class SourceVerifier(BaseAgent):
    """Checks every quote against its source page (no LLM)"""

    description: str = "Checks every quote and date against its source page (no LLM)."

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        research = ctx.session.state.get("research", "")
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            (RUNS_DIR / "last_research.md").write_text(str(research), encoding="utf-8")
            result = await verify_research(research, cache_dir=CACHE_DIR)
            facts = result.get("facts", [])
            report = format_verification(result)
            # counts of the last iteration; None = nothing could be counted
            counts = result["counts"] if result["status"] in ("ok", "empty") else None
            # redirect link -> real page URL; used only when writing the output
            urls = resolved_urls(result)
        except Exception as exc:
            report = f"SOURCE VERIFICATION: ERROR ({type(exc).__name__}: {exc})"
            counts, urls, facts = None, {}, []
        state = ctx.session.state
        trace = list(state.get("trace") or [])
        trace.append({
            "iteration": int(state.get("iterations") or 0) + 1,
            "research": str(research),
            "verification_counts": counts,
            "verification_report": report,
            "facts": [{k: f.get(k) for k in TRACE_FACT_FIELDS} for f in facts],
        })
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"verification": report,
                                              "verification_counts": counts,
                                              "resolved_urls": urls,
                                              "trace": trace}),
        )


# --------------------------------------------------------------------------
# LLM agents
# --------------------------------------------------------------------------
researcher = Agent(
    name="researcher",
    model=gemini(MODEL),
    instruction=RESEARCHER_INSTRUCTION,
    tools=[google_search],
    generate_content_config=model_config(),
    before_model_callback=limit_before_model,
    after_model_callback=limit_after_model,
    output_key="research",
    include_contents="none",
)

judge = Agent(
    name="judge",
    model=gemini(MODEL),
    instruction=JUDGE_INSTRUCTION,
    output_schema=JudgeFeedback,
    output_key="judge_feedback",
    include_contents="none",
    generate_content_config=model_config("JUDGE_THINKING_LEVEL", thinking_default="low"),
    before_model_callback=limit_before_model,
    after_model_callback=limit_after_model,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

research_loop = LoopAgent(
    name="research_loop",
    description="Researches the company, verifies each fact against its source, and repeats until the judge passes.",
    sub_agents=[
        researcher,
        SourceVerifier(name="source_verifier"),
        judge,
        EscalationChecker(),
    ],
    max_iterations=3,
)

writer = Agent(
    name="writer",
    model=gemini(WRITER_MODEL),
    description="Writes the final Markdown dossier from verified research.",
    instruction=WRITER_INSTRUCTION,
    tools=[load_seller_cases, check_dossier_format],
    before_agent_callback=prepare_writer,
    generate_content_config=model_config("WRITER_THINKING_LEVEL"),
    before_model_callback=limit_before_model,
    after_model_callback=limit_after_model,
    include_contents="none",
    output_key="dossier_md",
)

root_agent = SequentialAgent(
    name="dossier_pipeline",
    sub_agents=[research_loop, writer],
    before_agent_callback=init_state,
    after_agent_callback=finalize_run,
)