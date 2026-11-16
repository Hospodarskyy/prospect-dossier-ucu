"""judge (LLM): does it pass good research and fail bad research?

The judge is evaluated by eval/eval_judge.py (paid, about $0.05): a clean
research text is corrupted in known ways (mutations), so the right verdict is
known by construction. This module reads the latest saved result; it does not
call the model.
"""
from .common import RESULTS_DIR, component, read_json


def latest_result() -> tuple[str, dict] | tuple[None, None]:
    files = sorted(RESULTS_DIR.glob("judge_*.json"))
    return (files[-1].name, read_json(files[-1])) if files else (None, None)


def evaluate(runs=None) -> dict:
    name, result = latest_result()
    if not result:
        return component("judge", "no saved result: run python -m eval.eval_judge", {})
    overall = result["overall"]
    groups = result.get("by_group") or {}
    metrics = {
        "result file": name,
        "model / thinking": f"{result.get('model', '?')} / {result.get('thinking_level', '?')}",
        "cases": overall["total"],
        "accuracy": overall["accuracy"],
        "precision of 'fail' (bad research caught, not good research rejected)":
            overall["precision"],
        "recall of 'fail' (share of bad research caught)": overall["recall"],
    }
    for group, m in groups.items():
        metrics[f"accuracy, {group} mutations ({m['total']})"] = m["accuracy"]
    rows = [{"mutation": r["mutation"], "group": r["group"], "expected": r["expected"],
             "got": r["got"], "ok": r["ok"], "judge summary": r.get("summary", "")[:160]}
            for r in result.get("rows", [])]
    notes = ["Positive class: 'fail' (the research must go back). Benign mutations must pass, "
             "structural and semantic ones must fail."]
    return component("judge", "Reads the research and the verification report and returns "
                     "pass or fail with the problems found.", metrics, rows, notes,
                     ["mutation", "group", "expected", "got", "ok", "judge summary"])
