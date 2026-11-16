# CRISP-DM log: Prospect Dossier

The project was built in short CRISP-DM cycles: a change, a measurement, a step back to
the phase where the problem came from. Sections 1-6 describe each phase as it stands now;
section 7 is the log of the iterations, oldest first.

**How this log was made.** It was compiled on 2026-11-16 from dated records: the history
of the judge eval (`eval/results/judge_*.json`, 16 runs from 2026-10-27 to 2026-11-13), the
project notes (`CLAUDE.md`, sections 5 and 7), the component eval (`eval/results/summary.md`)
and the saved runs (`eval/runs/`, `demo-data/runs/`). Numbers come from those files; where a
step was not measured, the entry says so. From now on the log is kept during the work:
`CLAUDE.md` section 1.1 tells the AI assistant to follow CRISP-DM, and the
`crisp-dm-iteration` skill adds each new iteration here.

## 1. Business understanding

**Problem.** Before a first contact, a sales person spends time researching the target
company by hand. The system takes a company name and domain and produces a short dossier
in which every fact can be checked.

**User.** A sales manager or consultant preparing for a first call. The seller in this
version is Metacortex, a fictional software company; its case studies are test data.

**Input.** A JSON request: company name, domain, and an optional context ("why this company,
what we bring").

**Output.** A dossier of about two pages: Snapshot, Recent news, Tech signals, Key people,
Likely pains, Metacortex angle (how the seller could help, with 1-2 case studies and
questions for the call), What changed; plus `result.json` with counts and costs.

**Success criteria and where they stand** (component eval of 2026-11-13, 6 runs):

| Criterion | Target | Result |
|---|---|---|
| every fact has a source and the quote is on the page | 100% | grounded rate 0.885 after the 1st iteration, 1.0 in the final dossier |
| no data means `[Pending]`, never invented | fictional company: 0 facts | 0 facts with a source for Zorblax |
| news no older than 90 days | 100% | 1.0 of dated news |
| people: only name and public role | always | checked by the format check and the judge |
| repeated request shows What changed | always | 1.0 (1 repeated request) |
| cost per dossier | at most $0.40 | mean $0.131, max $0.209 |
| time per dossier | at most 9 minutes (540 s) | mean 201 s, max 311 s |

## 2. Data understanding

The agent has no fixed data set: every dossier is built from live web search (Google Search
through Gemini grounding) and from the pages it cites. What the data turned out to be:

- **Search links are redirects.** Grounding returns `vertexaisearch` redirect URLs, not the
  pages; they are resolved to the real URL before the dossier is written.
- **Some pages cannot be read by a script.** Sites behind bot protection return a challenge
  page (HTTP 403 or a "Just a moment..." page) instead of the content. A fact with such a
  source cannot be checked and is marked `unreachable`, not `not_found`.
- **Pages change.** The judge eval uses a fixed research text, but its sources are live:
  between two runs the Plausible team page changed from 10 to 11 people (iteration 3).
- **News is thin.** The researcher searches mostly on the company's own site; "Recent news"
  had a supported item in 4 of 5 real runs, and dates are often missing on the page.
- **Third-party pages** (reviews, competitors' blogs) are used as sources; they are not
  filtered out.
- **Languages.** Sources for a Ukrainian company are partly in Ukrainian; the dossier is in English.
- **Seller data.** The case studies are 6 invented entries (`demo-data/config/seller_cases.md`)
  with industry, technologies, problem and result.

## 3. Data preparation

At run time (scripts, no model):

- **Request:** JSON parsed and checked; the domain is normalized (case, `www.`, URL, port,
  internationalized names) and rejected if unsafe, because it becomes part of a file path.
- **Pages:** fetched, HTML turned into text, whitespace and number formats normalized
  (`30,000` = `30k`) before the quote is searched; bot-challenge pages detected.
- **Memory:** the facts of each dossier (no `[Pending]`, hypotheses or angle) are saved as
  `state/dossiers/<domain>.json` and given to the writer on the next request.

For evaluation (`eval/data/`); no public data set fits the task, so the data is synthetic
or labelled by hand:

| Data set | Size | How it was made |
|---|---|---|
| requests for the parser | 16 | written by hand: valid, edge and invalid inputs |
| SourceVerifier cases | 151 + 12 | 151 synthetic cases from 20 real pages of the eval runs, label known by construction (exact quote, noise, swapped words, quote from another page, overstated claim, changed number, dates); 12 real facts labelled by hand |
| judge mutations | 13 | one correct research text corrupted in controlled ways |
| case-study profiles | 10 | company profiles with the relevant case, labelled by hand |
| end-to-end companies | 6 | 4 real companies of different industries and sizes, a repeated request, a fictional company |

## 4. Modeling

```
init_state (script) → research loop, at most 3 iterations:
  researcher (LLM + Google Search) → SourceVerifier (script) → judge (LLM, JSON) → stop check (script)
→ writer (LLM + load_seller_cases, check_dossier_format) → finalize_run (script)
```

Main choices and the evidence behind them (details in section 7):

- **A loop with a judge**, because a single research pass often cites pages that do not
  support the claim; the judge sends the research back with the list of problems.
- **SourceVerifier as a script**, because the judge cannot open pages: it opens every cited
  page and checks the quote and the date; the judge trusts its report.
- **No formatter agent**: it changed URLs (iteration 6); `result.json` is computed by a
  script from the dossier and validated with Pydantic.
- **Model: Gemini Flash** (now `gemini-3.8-flash` through the Gemini API), chosen on cost
  (iteration 7); **judge thinking `low`**: same accuracy, 69% fewer thinking tokens (iteration 5).
- **Hard stops** before and after every model call (50 calls, $0.40, 540 s) and a research
  stop (15 searches or 70% of the budget), so a run cannot run away.
- **What changed** compares with the memory; which news is new is decided by a script
  (iteration 9).

## 5. Evaluation

Every component has its own metrics (`python -m eval.eval_components`, free; full table in
`eval/results/summary.md`; the reasoning behind each metric is in the report):

| Component | Main result |
|---|---|
| request parsing | 16/16 |
| researcher | grounded 0.885 at the 1st iteration, 1.0 final; misquotes 0; fictional company 0 invented facts |
| SourceVerifier | `supported` precision and recall 1.0; weak-support flag: recall 0.54 on synthetic cases (subtle overstatements 0/20), precision 0.4 on real facts |
| judge | 13/13 mutations |
| writer | format 6/6; 97.6% of fact bullets match a supported fact; case studies: precision 0.6, recall 0.33 |
| load_seller_cases | hit@1 1.0 on profiles and on the writer's real arguments (0.8 before iteration 11) |
| memory | 1.0 on first and repeated requests |
| whole pipeline | 5 ok, 1 partial (search limit); mean $0.131, 201 s |

Open weaknesses found by the evaluation: the weak-support flag is noisy; subtle overstatements
pass the SourceVerifier; the writer rarely cites case studies; pages behind bot protection
cannot be checked; a repeated dossier is a new snapshot, so facts not found again drop out.

## 6. Deployment

- **Service:** FastAPI with `POST /run` and `GET /health` in Docker (`service/Dockerfile`);
  requests are files in `inbox/`, results go to `outbox/<date>/<run_id>/`. Checked on
  2026-11-12: build ok, a Plausible run through `POST /run` ok, $0.124, 3 min 24 s.
- **Demo:** a Streamlit app (`app.py`) that replays saved runs for free (agent graph from
  `trace.json`, state of each node on hover) and runs new requests with a live graph.
- **Storage:** local files only (`data/storage/`).

## 7. Iterations

### 1. 2026-10-27 to 10-29: first loop and the judge eval
- **Phase:** Business understanding -> Modeling, Evaluation
- **Finding:** a single research pass is not enough to trust the facts; a reviewer is needed.
- **Change:** research loop (researcher + judge, `LoopAgent`); a judge eval that corrupts a
  correct research text ("mutations") so the right verdict is known by construction.
- **Result:** first judge eval on 2026-10-27 (1 case); 10 mutations by 2026-10-29.
- **Did not work:** nothing recorded.
- **Next:** check the judge on more kinds of errors.

### 2. 2026-10-29: the judge failed a correct research
- **Phase:** Evaluation -> Data preparation
- **Finding:** the baseline (correct) research got `fail`: "One news item has a date in the
  future relative to today's date (2026-10-27)".
- **Change:** the eval uses a fixed "today" that matches the fixture (`TODAY` in `eval/eval_judge.py`).
- **Result:** 10/10 (`judge_20261029_164126.json`).
- **Did not work:** nothing.
- **Caveats:** one fixture research text.
- **Next:** none.

### 3. 2026-11-06: live pages changed under the eval
- **Phase:** Evaluation -> Data understanding
- **Finding:** with the SourceVerifier report in the judge's input, the baseline and
  `reverse_bullets` failed: "the cited source page specifies a team of 11", the fixture said 10.
  Accuracy 0.8.
- **Change:** the fixture was updated to the page.
- **Result:** 10/10 again (`judge_20261106_155834.json` → later runs).
- **Did not work:** nothing.
- **Caveats:** the judge eval still depends on live pages.
- **Next:** freeze page snapshots in `data/fixtures/pages` (open).

### 4. 2026-11-06: a date that is not on the page
- **Phase:** Evaluation -> Modeling
- **Finding:** a new mutation `fake_date` (a news date that the page does not show) passed the
  judge: "All research criteria are fully satisfied". Accuracy 10/11.
- **Change:** the date check of the SourceVerifier (date on the page: exact, month or missing)
  was made a reason to fail in the judge's input; the exact diff was not recorded.
- **Result:** 11/11 four minutes later (`judge_20261106_160750.json`).
- **Did not work:** nothing.
- **Caveats:** the check asks whether the date is on the page, not whether it belongs to this news item.
- **Next:** open.

### 5. 2026-11-09: judge thinking level
- **Phase:** Modeling
- **Finding:** thinking tokens are a large part of the cost.
- **Change:** judge `thinking_level="low"`; the researcher gets no conversation history
  (`include_contents="none"`).
- **Result:** judge eval 11/11 with the default thinking and with `low`; thinking tokens on
  the 11 cases 10,554 → 3,243 (-69%), two runs each.
- **Did not work:** nothing.
- **Caveats:** measured on the judge eval only.
- **Next:** the writer stays on the default (its share was not worth the risk).

### 6. 2026-11-09: the formatter changed URLs
- **Phase:** Evaluation -> Modeling
- **Finding:** an LLM formatter (an agent with an output schema that wrote `result.json`)
  "fixed" the base64 padding in 3 of 4 URLs of a run, so the links no longer matched.
- **Change:** the formatter was removed; all fields of `result.json` are computed by a
  script from the dossier and validated with Pydantic.
- **Result:** URLs are copied exactly; one model call less per run.
- **Did not work:** nothing.
- **Next:** none.

### 7. 2026-11-09 to 11-11: model choice by cost
- **Phase:** Evaluation -> Modeling
- **Finding:** on an earlier Flash model (3.5 on Vertex AI) one iteration cost $0.387 of the
  $0.40 limit; one run hit the cost hard stop at $0.444 after 25 searches in one iteration.
- **Change:** a cheaper Flash model: 3.7 on Vertex AI ($0.112, 2 iterations, 7 searches),
  then `gemini-3.8-flash` through the Gemini API for this version.
- **Result:** Plausible on 3.8 (2026-11-11): ok, 13/13 facts confirmed, $0.101, 157 s.
- **Did not work:** nothing.
- **Caveats:** the cost hard stop is checked before a call, so one call can still go over the limit.
- **Next:** open.

### 8. 2026-11-09: a partial run that could not be explained
- **Phase:** Evaluation -> Data understanding
- **Finding:** a run ended `partial` with Key people marked unsourced, and the cause could not
  be found because the verification report was not saved; one guess (the server's IP is
  blocked) was checked and rejected.
- **Change:** `trace.json` per run (each iteration's research, the check of every source,
  the judge's feedback); bot-challenge pages are detected and marked `unreachable`.
- **Result:** later problems can be traced; blocked pages are counted in `usage.blocked_pages`.
- **Did not work:** the cause of that run stays unknown.
- **Next:** none.

### 9. 2026-11-09 to 11-16: What changed reported things that did not change
- **Phase:** Evaluation -> Modeling
- **Finding:** in a repeated request, a news item of 2026-10-02 was listed as new although the
  previous dossier was from 2026-11-09, and a different sample of people ("Sanne -> Bogdan")
  was listed as a change. The prompt itself gave "a person who is no longer listed" as an example of a change.
- **Change:** a script (`news_since`) passes the writer only the news dated after the previous
  dossier (2026-11-09); the prompt now says a different set of people is not a change (2026-11-16).
- **Result:** memory eval 1.0; the repeated Plausible run reports "No material changes since 2026-11-12".
- **Did not work:** nothing.
- **Caveats:** only one repeated request in the eval.
- **Next:** a repeated dossier is a new snapshot; carrying over facts that are still on their
  pages is not done (open).

### 10. 2026-11-13: component evaluation
- **Phase:** Evaluation
- **Finding:** an end-to-end check does not say which part is weak. In a real run (2026-11-11)
  the judge passed a claim that said more than its quote ("... due to its high cost and
  conflict with privacy principles", the quote only said it was expensive).
- **Change:** one evaluation module per component (`eval/components/`); 6 recorded runs
  ($0.787); the SourceVerifier data set; two overstatement mutations for the judge.
- **Result:** the table in section 5. The judge caught both overstatement mutations (13/13),
  so the flaw seen in the real run did not reproduce on synthetic data. New weaknesses: the
  weak-support flag (precision 0.4 on real facts, subtle overstatements 0/20), the writer's
  case recall 0.33, the case selection (below).
- **Caveats:** 6 runs; the 12 real facts were labelled by the AI assistant, with a note on each label.
- **Next:** case selection (next entry); the weak-support threshold is not calibrated (open).

### 11. 2026-11-16: case selection missed the right case
- **Phase:** Evaluation -> Modeling
- **Finding:** `select_candidates` did not put cs-06 (industry "HealthTech") in the top 5 for
  Doctolib, because the writer passed `industry="Healthcare"` and industries had to match
  exactly; it also kept the final dot of words ("payments." ≠ "payments"). hit@1 on the
  writer's real arguments 0.8, on the profiles 0.8 (MRR 0.825).
- **Change:** industry synonyms (`INDUSTRY_GROUPS`: "Healthcare" ~ "HealthTech", "Retail" ~
  "E-commerce"); dots stripped at the ends of words (`dossier_agent/seller_cases.py`).
- **Result:** hit@1 and MRR 1.0 on both (free recomputation); Doctolib: cs-06 first; other
  components unchanged.
- **Did not work:** matching the case title as well: Supabase then ranked cs-01 above the
  relevant cs-02 (both scored on "scaling"), so it was dropped.
- **Caveats:** the profiles were labelled by whoever saw the gaps, so the synonyms cover
  exactly them; the independent evidence is Doctolib from a real run. Whether the writer now
  cites better cases needs a paid re-run of `collect_runs`.
- **Next:** that re-run.

### 12. 2026-11-16: one run looked like two invocations
- **Phase:** Deployment -> Modeling
- **Finding:** when the agent was run through `adk eval`, ADK saw two invocations per run:
  the events of the two script agents (EscalationChecker, SourceVerifier) had no `invocation_id`.
- **Change:** both pass `invocation_id=ctx.invocation_id`; a test checks it.
- **Result:** one run = one invocation.
- **Did not work:** nothing.
- **Next:** none.
