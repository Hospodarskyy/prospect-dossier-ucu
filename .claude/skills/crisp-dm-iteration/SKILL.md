---
name: crisp-dm-iteration
description: Record one CRISP-DM iteration of the Prospect Dossier project (finding, change, metric before and after, what did not work, next step). Use after a change the user keeps, after an evaluation that found a problem, or when the user asks to log progress.
---

# Record a CRISP-DM iteration

The project follows CRISP-DM, and the report must show it. Each iteration is a
short, factual entry; the numbers come from real runs, never from memory.

## Phases in this project

| Phase | Here it means |
|---|---|
| Business understanding | what the sales person needs before a first call; success = every fact sourced, cost and time limits (README) |
| Data understanding | what web search and the cited pages really return (bot protection, missing dates, third-party pages); the seller's case studies |
| Data preparation | request parsing, page fetching and text cleaning, memory records, eval data sets (`eval/data/`) |
| Modeling | the agents, prompts, tools, model and thresholds (`dossier_agent/`) |
| Evaluation | component eval (`run-eval` skill), judge eval, end-to-end runs |
| Deployment | Docker service, Streamlit demo |

## Steps

1. Collect the facts: what showed the problem (an eval metric, a run, the user),
   what was changed (files), the metric before and after (from `run-eval`), and
   any attempt that was reverted and why. Ask the user if something is unknown.
2. Write the entry in English with this template:

   ```markdown
   ### <next number>. <YYYY-MM-DD>: <short title>
   - **Phase:** <phase that found it> -> <phase that changed>
   - **Finding:** <what was wrong, with the number and the input that shows it>
   - **Change:** <what changed, file names>
   - **Result:** <metric: before -> after; other components unchanged or not>
   - **Did not work:** <attempt, why it was dropped> (or "nothing")
   - **Caveats:** <limits of the evidence, e.g. labels made by whoever saw the gap>
   - **Next:** <open question or the run still needed, e.g. a paid re-run>
   ```

3. Add it to the iterations log of `docs/crisp-dm.md` (newest last), and update
   the phase section above it if the iteration changes what that phase says.
4. Add one line to `CLAUDE.md` (in English): section 5 (what was done) or
   section 7 (known weaknesses: mark the item as fixed with the date).

Example (2026-11-16): the component eval showed that `select_candidates` missed
cs-06 for Doctolib (`industry="Healthcare"`, case industry "HealthTech") and
kept the dot of "payments."; industry synonyms and the word fix raised hit@1 on
the writer's real arguments from 0.8 to 1.0; matching the case title too was
dropped because Supabase then ranked cs-01 above the relevant cs-02.
