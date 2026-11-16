---
name: run-eval
description: Recompute the component evaluation of the Prospect Dossier agent for free and compare it with the previous result. Use after any change to dossier_agent/ or eval/, before saying a change works, and when the user asks how a change affected quality.
---

# Run the component eval and compare

The component eval scores every part of the agent on saved runs and labelled
data (`eval/runs/`, `eval/data/`). Recomputing it costs nothing: no model call,
no web request.

1. Keep the current result as the baseline:
   `cp eval/results/summary.json eval/results/summary_before.json`
2. Recompute: `python -m eval.eval_components`
   (one component only: `--only case_selection`, `--only writer researcher`).
3. Compare:
   `python .claude/skills/run-eval/compare.py eval/results/summary_before.json eval/results/summary.json`
4. Report to the user, in this order:
   - every metric that got worse (a regression), with the rows that explain it;
     whether lower or higher is better follows from the metric's name
     (misquote rate, dead links, cost and time are better when lower);
   - the metrics that improved, before -> after;
   - components that did not change, in one line.
   Look at the changed rows before explaining a number: the reason is usually
   one or two inputs.
5. A regression is not accepted silently: find its cause, then fix the change
   or ask the user. Example (2026-11-16): matching the case title as well made
   Supabase rank cs-01 above the relevant cs-02, so the title matching was dropped.
6. After a change that the user keeps, record it with the `crisp-dm-iteration` skill.

Never run the paid commands without the user's permission:
`python -m eval.collect_runs` (about $0.80, new agent runs) and
`python -m eval.eval_judge` (about $0.06). They are needed only when the
change affects what the model does (prompts, model, tools); say so and ask.
