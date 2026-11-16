# CLAUDE.md — Prospect Dossier (university version, UCU GenAI Assignment 1)

This file is the context for Claude Code. Read all of it before starting work.
Branch `ucu-assignment`. Branch `main` is the working version for CHI (GEAR): GCP, bucket,
Cloud Run, Telegram, CHI case studies. **Bring nothing from CHI into this branch.**
How to run the system and what it does: `README.md` (for the teacher, in English).

---

## 1. How to work with me

- Explain things to me. Code, comments, docstrings, agent prompts, README,
  this file and the skills are in English.
- You write the code, but **only after the design of the item has been discussed and agreed**.
- If context is missing, ask first.
- A component is done only when it has a test (pytest, offline) and/or an eval
  (skills `write-tests`, `run-eval`).
- Do not invent facts about ADK: check adk.dev and the source of the pinned version
  (`.venv/lib/python3.12/site-packages/google/adk`), skill `verify-adk`. Verified facts: section 6.
- Paid runs (LLM) only with my permission. Never show secrets from `dossier_agent/.env`;
  I edit `.env` myself. Commits only when I ask.

### 1.1 Process: CRISP-DM

Work on this project follows CRISP-DM. The phases as they apply here are in the
`crisp-dm-iteration` skill.

1. Before a task, name its phase in one line ("Modeling: the writer prompt").
   If the task changes what the agent is for, its limits or its scope, that is
   Business understanding: ask before doing it.
2. Rules per phase:
   - Data understanding: look at real data before changing code that handles it
     (trace.json, cached pages, eval/runs), not at assumptions about it.
   - Data preparation: a change to eval data or labels says who labelled and how;
     never change a label to make a metric pass.
   - Modeling: one change at a time, so its effect can be measured. A change to
     prompts, model or tools needs a paid run to measure: say so and ask.
   - Evaluation: after every change run the free component eval (`run-eval`) and
     compare with the previous result. A regression is never accepted silently.
     Say what limits the evidence (few inputs, labels made by us).
   - Deployment: after a change to the service or the demo, check the Docker
     build or the demo tests still pass.
3. When the eval finds a problem, trace it back to the phase it comes from
   (a page behind bot protection is Data understanding; a wrong rule in a prompt
   is Modeling) and say so: the fix belongs there.
4. When the user keeps a change, record the iteration (`crisp-dm-iteration`).
   Numbers in the record come from a run in this session or from eval/results,
   never from memory.

## 2. What the project is

Given a company name and domain, the agent prepares a dossier before the first contact:
business, news, tech signals, people, likely pains, and an angle for the seller with case
studies. Every fact has a URL and a verbatim quote; a script checks the quote on the page,
and the judge does not let the dossier through until the facts are confirmed. The agent
remembers earlier dossiers and shows what changed.

The seller is **Metacortex** (the fictional software company from "The Matrix"). The case
studies are invented, marked TEST, with URLs on `example.com`. Never invent case studies
under the name of a real company.

Requirements (formerly from the GEAR spec, now in the README): every fact has a URL, no
data means `[Pending]`; news at most 90 days old; for people only name and public role; a
fictional company gets an honest `[Pending]`; a repeated request gets "What changed";
at most $0.40 and 9 minutes per dossier.

**UCU assignment (GenAI Assignment 1, PDF with the user; checked 2026-11-13):**
- Describe the components: data-flow diagram, purpose / input / output of each, model and
  external tool calls, the path of one request.
- Evaluate **every component**; the choice of metrics is graded; explain high and low
  scores and how to improve them.
- CRISP-DM must be visible in the report, and the instructions to follow CRISP-DM must be
  in the agent's file (this CLAUDE.md).
- Create SKILLS for agentic development (`.claude/skills/`).
- Data: check existing datasets first, then synthetic ones (explain in the report).
- Submission: code + a short report (diagrams, business logic in scope, eval results) +
  a video of at most 10 minutes (requirements, components, demo, eval, how the agent is set up).
- Points: understanding of the system 7, prototype 7, evaluation 7, work with the AI assistant 4.

## 3. Current state of the code

```
dossier_agent/
  agent.py          # root_agent = SequentialAgent(research_loop, writer); init_state, finalize_run,
                    # tools load_seller_cases / check_dossier_format, limit callbacks, gemini() with retry
  instructions.py   # RESEARCHER / JUDGE / WRITER_INSTRUCTION ({seller?}, {angle_section?})
  schemas.py        # JudgeFeedback; RunResult/DossierData (result.json, Pydantic, extra=forbid)
  verification.py   # SourceVerifier: page fetch, quotes, dates, bot-check pages
  format_check.py   # check_dossier_format / check_dossier_urls / check_dossier (angle_section is a parameter)
  request.py        # parse_request(json_text) -> company, domain, context; normalize_domain
  storage.py        # LocalStorage (STORAGE_ROOT, default data/storage)
  memory.py         # load_previous_dossier / save_dossier / extract_facts / news_since
  outbox.py         # build_data / build_pending_human / build_result / write_outbox; AGENT_NAME
  seller_cases.py   # "# Seller: <name>" + case studies; angle_section(seller); select_candidates (<= 5),
                    # INDUSTRY_GROUPS (industry synonyms)
  limits.py         # Limits (env), usage, hard_stop_reason, research_stop_reason
  pricing.py        # API_PRICES / VERTEX_PRICES by model_version; use_vertex(); fallback = most expensive
service/            # FastAPI POST /run + GET /health, queue inbox→processing→processed|failed,
                    # runner (RunConfig max_llm_calls + wait_for, on_event for the demo), Dockerfile
app.py              # Streamlit demo: Past runs (free, graph replay from trace.json) and New run
                    # (paid, live graph through on_event); streamlit only in requirements-dev
demo_app/           # runs.py (reads the outbox), graph.py (Step with info for the cards, GraphState,
                    # steps_from_run / steps_from_event, graph_dot), component.py (HTML for
                    # st.iframe: viz.js@3.31.0 from jsDelivr + state cards on hover)
demo-data/config/seller_cases.md   # seller Metacortex + 6 test case studies
demo-data/runs/     # sample runs for the demo (Plausible x2 on 3.8, Zorblax); Metacortex era only
data/fixtures/      # research_plausible.md (judge eval), research_zorblax.md
data/storage/       # (not in git) config/, state/dossiers/, inbox/…, outbox/
eval/               # component eval (see README "Tests and evaluation"):
  collect_runs.py   #   PAID ~$0.8: 6 companies (companies.json) → eval/runs/<id>/ (in git),
                    #   separate storage eval/storage (not in git), seed memory for Plausible
  eval_components.py#   free: metrics of every component → eval/results/summary.md/.json
  components/       #   one module per component, evaluate(runs) -> dict; common.py is shared
  build_verifier_set.py # free: pages of the eval runs → eval/data/verifier/ (synthetic)
  data/             #   companies.json, requests.jsonl, case_profiles.json,
                    #   verifier_manual.jsonl (12 real facts, labelled by Claude 2026-11-13)
  eval_judge.py     #   PAID ~$0.06: 13 mutations (+ overstate_claims, overstate_one_subtle)
scripts/usage_report.py  # tokens/searches/$ from dossier_agent/.adk/session.db
tests/              # 515 offline tests (pytest, pytest.ini: pythonpath=.); conftest: temporary
                    # storage with the demo cases, price backend = Gemini API; test_demo_app also AppTest
.claude/skills/     # skills for Claude Code: run-eval (+ compare.py), crisp-dm-iteration, verify-adk,
                    # write-tests
docs/               # report.md (the report: architecture, walkthrough, evaluation, CRISP-DM summary,
                    # AI assistant), crisp-dm.md (CRISP-DM log); diagrams are Mermaid inside the Markdown
```

### Pipeline

```
init_state (before_agent_callback on root, no LLM):
  JSON input (invalid → input_error + stop without LLM); run_id (uuid4 unless the service gave one),
  started_at, trigger (inbox | manual); seller, angle_section ("<seller> angle"),
  seller_cases (file config/seller_cases.md is required, otherwise ConfigError);
  prior_knowledge, previous_dossier_date (state/dossiers/<domain>.json)
research_loop = LoopAgent(max_iterations=3):
  researcher         google_search, include_contents="none" → "research"
  SourceVerifier     no LLM → "verification", "verification_counts", "resolved_urls", trace
  judge              output_schema=JudgeFeedback, thinking low → "judge_feedback" (pass|fail)
  EscalationChecker  iterations += 1; pass or research stop → escalate
writer               tools=[load_seller_cases, check_dossier_format]; before: prepare_writer
                     (new_news = news newer than the previous dossier) → "dossier_md"
finalize_run (after_agent_callback on root, no LLM): format checked again;
  replace_urls (Google redirect → real URLs); memory; outbox/<date>/<run_id>/
  report.md (+ Sources) + result.json + trace.json
```

Hard stops (callbacks before/after every model call): 50 calls, $0.40, 540 s;
research stop: 15 searches or 70% of the budget. Model: `Gemini(model, retry_options)`:
retries on 408/429/5xx, `MODEL_ATTEMPTS` (default 4).

## 4. Decisions already made

- **Model access:** Gemini API key by default; Vertex works through `.env`
  (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`). GCP labels and `AGENT_ID` removed; `result.json`
  has `agent = "prospect-dossier"`.
- **Model:** `MODEL=gemini-3.8-flash`. Through the Gemini API a request for `gemini-3.7-flash`
  is served by 3.8, a request for `gemini-3.5-flash` by 3.6. Prices of 3.8 and 3.6: $0.75 / $3.75
  per 1M until 2026-12-31, then $1.50 / $7.50. An unknown model is priced at the most expensive rate.
- **Storage:** local only (`STORAGE_ROOT`). No buckets, Cloud Run, Scheduler or Telegram.
- **Deployment:** Docker locally (`service/Dockerfile`, built from the root, `data/` mounted).
- **Demo:** the Streamlit app (`app.py`) with the agent graph; `adk web` for manual runs.
- **Seller:** in the case studies file (`# Seller: Metacortex`), not in `.env`.
- **No formatter (LLM):** `data` in `result.json` is computed by a script from the dossier.
- **No SkillToolset:** the format rules are in the writer's instruction, the check is a function tool.
- **Checks are scripts, not the model:** sources (SourceVerifier), format and URL provenance.
- **The judge reports all problems at once**; `weak_support` is a hint, not a reason to fail.
- **What changed:** only changes in the company, `<what>: <before> -> <now>`; news only
  from the NEW NEWS list (script `news_since`); a different set of people is not a change;
  nothing changed → `- No material changes since <date>.`
- **Memory** (`state/dossiers/<domain>.json`, one version, overwritten): the facts of the
  dossier (no `[Pending]`, hypotheses, angle, What changed); saved also when the judge did not pass.
- **Service:** one `POST /run` = one file from the inbox = one run; ok|partial → processed/,
  invalid input → failed/, technical error → one retry, then failed/.

## 5. What next

1. ✅ Remove GCS, Telegram, Cloud Run (2026-11-11).
2. ✅ CHI → Metacortex (2026-11-11).
3. ✅ API key, retries, prices, no labels (2026-11-11). Plausible run on 3.8 Flash
   (2026-11-11): ok, 13/13 facts confirmed, $0.101, 157 s, 4 searches (grounding).
4. ✅ README, this file, GEAR spec removed (2026-11-12).
5. ✅ Docker (2026-11-12): `docker build` ok; `/health`, empty queue (`idle`) and a Plausible
   run through `POST /run`: ok, $0.124, 3 min 24 s, files in `data/` owned by the user.
6. ✅ Component eval (2026-11-13): `eval/` (own scripts instead of `adk eval`, because
   response_match makes no sense for web research). Runs $0.787, judge 13/13. Next:
   the report with the explanation of the scores.
   **CRISP-DM iteration (2026-11-16), case selection:** `_words` strips dots at the ends of a
   word ("payments." = "payments"), `INDUSTRY_GROUPS` holds industry synonyms ("Healthcare" ~
   "HealthTech", "Retail" ~ "E-commerce"). Free recomputation: profiles hit@1 0.8 → 1.0,
   MRR 0.825 → 1.0; eval runs hit@1 0.8 → 1.0, MRR 0.8 → 1.0 (Doctolib: cs-06 not in the top 5 →
   1st). Matching the case title too caused a regression (Supabase: cs-01 overtook cs-02 on
   "scaling") → dropped. Caveat: the profiles were labelled by whoever saw the gaps (the
   synonyms cover exactly them); the independent evidence is Doctolib from a real run. The effect
   on the writer (which cases it cites) shows only after a paid re-run of `collect_runs`.
   Also ported from CHI (2026-11-16): `invocation_id` in the events of EscalationChecker and
   SourceVerifier; the writer rule "a different set of people is not a change".
7. ✅ `eval_judge` on 3.8 Flash, thinking low (2026-11-12): 11/11, same as on 3.6; ~$0.045
   (`eval/results/judge_20261112_153321.json`).
8. ✅ Streamlit demo (2026-11-12): `python -m streamlit run app.py` (not a bare `streamlit`:
   the Mac has global copies without google-adk). Zorblax run through the form: ok, $0.021, 37 s.
   Old runs of 2026-11-09 (CHI era) are shown without a trace; do not put them in
   `demo-data/runs`. The graph is custom HTML through `st.iframe` (in Streamlit 1.67
   `components.v1.html` is deprecated), state cards on hover; option B chosen over native
   tooltips (2026-11-12).
9. `docs/crisp-dm.md` (decision 2026-11-16): a separate file, the CRISP-DM log of the project;
   started 2026-11-16, compiled from dated records (judge eval history, these notes, eval results).
10. **Report (decision 2026-11-16):** one file in English (`docs/report.md`) instead of
    architecture.md + eval-report.md, plus the separate `docs/crisp-dm.md`; diagrams: Mermaid in the Markdown (agent tree, data flow,
    inbox/outbox); the graph with state cards is shown in the demo, not in the report. Data section: say honestly that the agent uses
    search results and the eval uses synthetic data and manual labels (no new dataset search).
11. **Submission (decision 2026-11-16):** a separate repository (e.g. `prospect-dossier-ucu`)
    with a new history: one commit with the state of `ucu-assignment`, no CHI commits (`9f94ad2`
    contains the CHI spec, the GCP project ID and the bucket). `CHI_GEAR_Agent` is private and stays so.

## 6. Verified facts about ADK 1.39.1 (do not check again)

- Instruction templates: only `{key}` and `{key?}`. There is **no** default-value syntax
  (`{key? default}`): set empty values in a callback.
- `before_agent_callback(callback_context) -> None`; writes to `callback_context.state`
  end up in state_delta. `callback_context.user_content` is the user's message.
- `escalate=True` is handled only by `LoopAgent`; `SequentialAgent` always goes on after the
  loop (the writer runs both after a pass and after 3 failed iterations).
- A custom `BaseAgent._run_async_impl` must be an async generator with `yield Event(...)`;
  without a yield: error `'coroutine' object has no attribute 'aclose'`.
- Function tool: a parameter typed `ToolContext` (or named `tool_context`) is not shown to
  the model, ADK fills it in → access to `tool_context.state`.
- `after_model_callback(callback_context, llm_response)`; `llm_response.grounding_metadata`
  is available (field `web_search_queries` = the list of real searches).
- `SkillToolset(skills=..., code_executor=None, additional_tools=[...])`.
  `run_skill_script` without a code executor returns `NO_CODE_EXECUTOR` and runs the script
  as a separate program (stdout). Function scripts are attached through `additional_tools`
  + in the SKILL.md frontmatter `metadata: adk_additional_tools: [name]`.
- `output_schema` together with tools is formally allowed in 1.39.1 (through a workaround
  `set_model_response`), but the project rule is to keep them in separate agents.
- `include_contents="default"` passes the whole conversation history to the agent (more
  expensive with every iteration). Data between agents goes through state and `{key}`.
- ADK Dev UI: the agent graph is not drawn (the UI calls a missing `/dev/build_graph_image`):
  a bug of this version, not Graphviz.
- One session in `adk web` = one request: `request` is written only once per session.
- If `before_agent_callback` returns `types.Content`, ADK sets `ctx.end_invocation = True`:
  sub-agents do not run; state written before the `return` is kept (`base_agent.py`,
  `_handle_before_agent_callback`).
- `google.adk.models.google_llm.Gemini(model=..., retry_options=types.HttpRetryOptions(...))`
  is the model of an LLM agent with request retries (`attempts` includes the first request).
- Through the Gemini API `llm_response.model_version` is the model that really answered
  (`gemini-3.7-flash` → `gemini-3.8-flash`, `gemini-3.5-flash` → `gemini-3.6-flash`).
- Callbacks `before_agent_callback` / `after_agent_callback` that change state produce a
  separate event from that agent (`author="dossier_pipeline"`) with a `state_delta` and no
  text; if the callback returns Content, the event has text. Google Search (grounding) is not
  visible as a function call in the events. Checked 2026-11-12 with a `MAX_LLM_CALLS=0` run (no cost).
- `adk eval` groups a run's events by `invocation_id` (`evaluation/evaluation_generator.py`):
  an event without `invocation_id=ctx.invocation_id` (custom BaseAgent) turns one run into
  two. `adk eval` loads the agent's `.env` with `override=True` (`cli/utils/envs.py`), so
  shell variables do not win there. Checked on `main` 2026-11-15.

## 7. Known weaknesses (for the report and further work)

- `weak_support` is noisy (7 of 13 facts on a clean 3.8 run); the threshold is not calibrated.
- The judge lets an overstatement through: "cannot rely on paid advertising due to its high
  cost **and conflict with privacy principles**", while the quote only says "expensive"
  (run 2026-11-11). Mutations overstate_* added 2026-11-13: the judge catches them (13/13),
  so the flaw does not reproduce on synthetic data.
- Eval 2026-11-13 (`eval/results/summary.md`):
  - ✅ (2026-11-16) `select_candidates`: `_words` kept the dot ("payments." ≠ "payments"),
    no synonyms: Doctolib `industry="Healthcare"` → cs-06 (HealthTech) not in the top 5.
  - weak_support on real facts: precision 0.4, recall 0.67 (a paraphrase = false alarm,
    "will become" → "is" missed); subtle overstatements in synthetic data: 0/20.
  - The number check looks at the whole page, not near the quote (number_changed 5/6).
  - The writer cites case studies only when backed by a fact → recall of relevant cases 0.33
    (Rozetka: none).
  - PostHog partial: search limit (21 > 15), judge fail → fail.
- Pains may rest on old posts (2020): the 90-day rule applies only to news.
- The date check only asks "is this date on the page", not "is it the date of this news item".
- News: the researcher searches mostly on the company's site → "Recent news" is often `[Pending]`.
- Number of searches: `grounding_metadata` is not always there (then taken from the model's
  own words, `searches_source: model_reported`, off by ±1); searches inside one call cannot be
  stopped, the limit of 15 can be exceeded in one iteration.
- The cost hard stop is checked BEFORE a call: one call can go over the limit.
- The judge eval depends on live pages; snapshots should be frozen in `data/fixtures/pages`.
- Third-party sources (competitors' blogs) are not filtered out.

## 8. Commands

```bash
pytest -q                            # offline tests
python -m streamlit run app.py       # demo: saved runs (free) and new ones (paid)
adk web                              # manual run; a new session for every request
python -m scripts.usage_report -n 3  # tokens, searches, $ of the last adk web sessions
uvicorn service.main:app --port 8080 # the service locally; curl -X POST localhost:8080/run
docker build -f service/Dockerfile -t prospect-dossier .
python -m eval.eval_components       # component eval (free)
python -m eval.eval_judge            # mutation eval of the judge (paid)
```

Before the first run: `mkdir -p data/storage/config && cp demo-data/config/seller_cases.md data/storage/config/`.
Test request: `{"company": "Plausible Analytics", "domain": "plausible.io"}`.
