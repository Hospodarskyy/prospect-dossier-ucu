# Prospect Dossier

A multi-agent system (Google ADK + Gemini) that prepares a short, source-backed
dossier on a company before a first sales call: what the company does, recent
news, tech signals, key people, likely pains, and how a seller could help.

Every fact in the dossier has a URL, and a script checks that its quote is
really on that page. A judge agent sends the research back until the facts
hold up. The agent remembers earlier dossiers and reports what changed.

The seller in this demo is **Metacortex**, the fictional software company from
the film *The Matrix*. Its case studies are invented test data
(`demo-data/config/seller_cases.md`, URLs on `example.com`).

## Pipeline

```
request (JSON) ──> init_state (script) ──> research loop, up to 3 iterations ──> writer ──> finalize (script)
                                           │ researcher      (LLM + Google Search) │      (LLM + 2 tools)
                                           │ SourceVerifier  (script: fetch pages, check quotes and dates)
                                           │ judge           (LLM, JSON verdict pass | fail)
                                           └ EscalationChecker (script: stop on pass or on a limit)
```

| Step | What it does |
|---|---|
| `init_state` | Parses the JSON request, loads the seller file and the previous dossier for this domain. |
| `researcher` | Searches the web and writes facts as `- claim (source: URL) (quote: "...")`. |
| `SourceVerifier` | No LLM. Opens every source URL and checks that the quote (and date) is on the page. Resolves Google redirect links to the real URLs. |
| `judge` | Reads the research and the verification report; returns `pass` or `fail` with the problems found. |
| `writer` | Writes the dossier. Tools: `load_seller_cases` (up to 5 matching case studies) and `check_dossier_format` (format, length, and that every URL comes from the research or the case list). |
| `finalize_run` | No LLM. Replaces redirect URLs with real ones, adds a Sources section, saves the memory, writes `report.md`, `result.json` and `trace.json`. |

Dossier sections, in order: Snapshot, Recent news, Tech signals, Key people,
Likely pains, Metacortex angle, What changed (+ Sources, added by the script).

### Rules the system enforces
- Every fact has a URL from the research; missing data is `[Pending]`, never invented.
- News is at most 90 days old; for people, only name and public role.
- A company with no public data gets an honest, mostly `[Pending]` dossier.
- A repeated request for the same domain fills "What changed".
- Hard stops per dossier: 50 model calls, $0.40, 9 minutes; the research loop
  also stops after 15 Google searches or 70% of the budget.

## Quick start (about 10 minutes)

Requirements: Python 3.12, a Gemini API key (https://aistudio.google.com/apikey).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example dossier_agent/.env          # then put your key into GOOGLE_API_KEY
mkdir -p data/storage/config
cp demo-data/config/seller_cases.md data/storage/config/

pytest tests/ -q                            # offline tests, no API calls
python -m streamlit run app.py              # demo app: saved runs (free) and new runs
adk web                                     # or the ADK dev UI: http://localhost:8000, pick dossier_agent
```

Without a key you can still open the demo app and replay the sample runs.

In `adk web`, start a new session and send a request as JSON:

```json
{"company": "Plausible Analytics", "domain": "plausible.io"}
```

`context` is optional (what the seller already knows or wants):
`{"company": "Plausible Analytics", "domain": "plausible.io", "context": "They may need help scaling ClickHouse"}`.
Use a new session for every request.

One dossier takes 2–4 minutes and costs $0.10–0.13 with `gemini-3.8-flash`
(Google Search: 5,000 free requests per month).

### Results

```
data/storage/
  outbox/<date>/<run_id>/report.md     the dossier (with real URLs and Sources)
  outbox/<date>/<run_id>/result.json   status, usage (tokens, searches, $), extracted data
  outbox/<date>/<run_id>/trace.json    every research iteration, verification and judge verdict
  state/dossiers/<domain>.json         memory: facts of the last dossier for this domain
```

`result.json` `status`: `ok` (judge passed, format valid), `partial` (a dossier
was written, but the judge did not pass or a limit stopped the run; what to
check by hand is in `pending_human`), `failed` (no dossier).

## Demo requests

| Request | Expected |
|---|---|
| `{"company": "Plausible Analytics", "domain": "plausible.io"}` | Full dossier, `Metacortex angle` cites 1–2 case studies. |
| the same request again | "What changed" compares with the first dossier. |
| `{"company": "Zorblax Dynamics", "domain": "zorblax-dynamics.io"}` | Fictional company: mostly `[Pending]`, nothing invented. |
| `{"company": "X"}` | `Invalid request: domain is required`, no model call. |

## Demo app (Streamlit)

```bash
python -m streamlit run app.py      # http://localhost:8501
```

- **Past runs** (free, no API key needed): every saved run from
  `data/storage/outbox/` (runs from the app, `adk web` and the service) and the
  sample runs in `demo-data/runs/` (Plausible Analytics twice, the second one
  with memory of the first; Zorblax Dynamics, a fictional company).
  For each run: the agent graph with the path the run took (iterations, judge
  verdicts, tools used), a **Replay** button that animates it step by step
  without calling the model, the metrics (model calls, searches, $, time), the
  dossier, every research iteration (facts with their verification status,
  the judge's verdict) and the raw `result.json` / `trace.json`.
- **New run** (paid, about $0.10–0.13): a form with company, domain and
  context; the graph is highlighted live while the agents work, with a log of
  each step. The run is saved and appears in Past runs.

Hover over a node to see its state values at that moment: the request and
memory (init_state), searches and facts (researcher), verification counts
(SourceVerifier), the verdict with its summary and problems (judge), the
decision (EscalationChecker), the dossier size and cited case studies (writer,
load_seller_cases), and status, cost and time (finalize_run). During a replay
or a live run the cards show the current iteration.

The graph is drawn in the browser with viz.js from cdn.jsdelivr.net, so the
page needs internet. The replay shows the order of the steps, not their real
timing (step times are not saved).

## Running as a service (Docker)

The same agent behind an HTTP endpoint with a file queue: put a request file
into `data/storage/inbox/`, call `POST /run`, and the result appears in
`data/storage/outbox/`. One call processes one request.

```bash
docker build -f service/Dockerfile -t prospect-dossier .
docker run --rm -p 8080:8080 --env-file dossier_agent/.env \
  -v "$PWD/data:/app/data" --user "$(id -u):$(id -g)" prospect-dossier

# in another terminal
mkdir -p data/storage/inbox
echo '{"company": "Plausible Analytics", "domain": "plausible.io"}' > data/storage/inbox/plausible.io.json
curl -X POST localhost:8080/run
```

Without Docker: `uvicorn service.main:app --port 8080`.

Queue rules: a finished run moves the file to `processed/` (status ok or
partial) or `failed/`; a technical failure (exception, timeout) is retried once.
`docker --env-file` reads `KEY=value` lines without quotes.

## Configuration (`dossier_agent/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `GOOGLE_API_KEY` | | Gemini API key. |
| `MODEL` | `gemini-3.8-flash` | Model of all agents. |
| `WRITER_MODEL` | `MODEL` | Optional separate model for the writer. |
| `JUDGE_THINKING_LEVEL`, `WRITER_THINKING_LEVEL` | judge `low` | `minimal`, `low`, `medium`, `high`; empty = model default. |
| `MODEL_ATTEMPTS` | `4` | Attempts per model request (retries on 429 / 5xx). |
| `MAX_LLM_CALLS`, `COST_LIMIT_USD`, `TIME_LIMIT_SECONDS`, `MAX_SEARCHES` | `50`, `0.40`, `540`, `15` | Hard stops. |
| `STORAGE_ROOT` | `data/storage` | Where memory, config, queue and results live. |

Vertex AI works instead of the API key: set `GOOGLE_GENAI_USE_VERTEXAI=TRUE`,
`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` (see `.env.example`).

To use another seller, change the first line of
`data/storage/config/seller_cases.md` (`# Seller: <name>`) and its case studies;
the dossier section becomes `<name> angle`.

## Tests and evaluation

Tests check that the code does what it should; the evaluation measures how good
each component's output is. Results and their discussion: `docs/eval-report.md`
(the generated tables: `eval/results/summary.md`).

```bash
pytest tests/ -q                       # offline tests: no model, no network

python -m eval.eval_components         # FREE: metrics of every component from the saved runs
python -m eval.collect_runs            # PAID (~$0.75): re-collect the 6 eval runs into eval/runs/
python -m eval.build_verifier_set      # free: rebuild the SourceVerifier set from their pages
python -m eval.eval_judge              # PAID (~$0.06): judge on 13 corrupted research texts
python -m scripts.usage_report -n 3    # tokens, searches and $ of the last adk web sessions
```

| Component | How it is evaluated |
|---|---|
| init_state (request parsing) | 16 labelled requests (valid, URLs, IDN, invalid ones): accuracy |
| researcher | 6 runs (5 real companies + 1 fictional): share of facts whose quote is on the cited page (1st and final iteration), misquotes, dead links, section coverage, news freshness, invented facts for the fictional company |
| SourceVerifier | labelled cases built from the pages of the eval runs (quote from the page, words swapped, quote from another page, overstated claim, changed number, dates) + hand-labelled real facts: precision / recall of "supported" and of the weak-support flag, date-check accuracy |
| judge | 13 mutations of a clean research text with a known right verdict: accuracy, precision / recall of "fail" |
| writer | the 6 runs: format validity, URL provenance, faithfulness of each fact bullet to a verified research fact, honesty about missing data, relevance of cited case studies |
| load_seller_cases | 10 labelled profiles + the writer's real arguments: hit@1, MRR |
| memory / What changed | first vs repeated request (seeded memory): What changed correct, memory saved |
| whole pipeline | status, judge passes at the 1st iteration, iterations, cost and time vs the limits |

`eval/runs/` (the collected runs) and `eval/data/` (labelled sets) are in git,
so the free metrics can be recomputed without an API key. The eval runs also
appear in the demo app (Past runs, "eval run").

## Project structure

```
dossier_agent/      the ADK agent (root_agent in agent.py)
  agent.py            pipeline, callbacks, tools, hard stops
  instructions.py     prompts of researcher, judge, writer
  verification.py     SourceVerifier: fetch pages, check quotes and dates
  format_check.py     dossier format and URL provenance checks
  memory.py           previous dossier, "What changed" news
  outbox.py           report.md / result.json / trace.json
  seller_cases.py     seller file and case study selection
  limits.py, pricing.py   usage accounting and cost limit
  request.py, storage.py, schemas.py
service/            FastAPI service (POST /run), file queue, Dockerfile, runner
app.py              Streamlit demo app
demo_app/           its logic: saved runs (runs.py), agent graph, steps and state values
                    (graph.py), the graph page with hover cards (component.py)
eval/               evaluation: collect_runs (paid), eval_components (free), eval_judge,
                    components/ (one module per component), data/ (labelled sets),
                    runs/ (collected runs), results/summary.md
tests/              offline pytest suite
scripts/            usage report
demo-data/config/   seller file (Metacortex, test data)
demo-data/runs/     sample runs for the demo app
data/fixtures/      research texts for the eval
docs/               CRISP-DM report
```

## Known limitations

- Recent news is often `[Pending]`: the researcher mostly searches the company's own site.
- The judge sometimes passes an overstated claim whose quote supports only part of it.
- The date check confirms that a date is on the page, not that it is the date of that news item.
- Searches happen inside one model call, so a limit cannot stop them midway:
  one iteration can go over the 15-search limit.
- The judge eval fetches live pages: a changed page can change the baseline.
