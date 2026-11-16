"""The whole pipeline: status, judge loop, cost and time against the limits."""
from dossier_agent.limits import Limits

from .common import component, mean, ratio


def evaluate(runs) -> dict:
    limits = Limits()
    rows = []
    for run in runs:
        usage, data = run.usage, run.data
        verdicts = []
        for it in run.iterations:
            fb = it.get("judge_feedback")
            verdicts.append(fb.get("status", "?") if isinstance(fb, dict) else "?")
        rows.append({"run": run.id, "status": run.result.get("status", "no result"),
                     "iterations": data.get("iterations"), "judge": " → ".join(verdicts),
                     "model calls": usage.get("llm_calls"), "searches": usage.get("searches"),
                     "cost $": usage.get("cost_usd"), "time s": usage.get("elapsed_seconds"),
                     "stop": usage.get("hard_stop") or usage.get("research_stop") or ""})
    n = len(rows)
    costs = [r["cost $"] for r in rows if isinstance(r["cost $"], (int, float))]
    times = [r["time s"] for r in rows if isinstance(r["time s"], (int, float))]
    metrics = {
        "runs": n,
        "status ok": ratio(sum(r["status"] == "ok" for r in rows), n),
        "status partial": ratio(sum(r["status"] == "partial" for r in rows), n),
        "status failed": ratio(sum(r["status"] not in ("ok", "partial") for r in rows), n),
        "judge passed at the 1st iteration": ratio(sum(r["judge"].startswith("pass")
                                                       for r in rows), n),
        "mean research iterations": mean(r["iterations"] for r in rows),
        "mean cost $": mean(costs), "max cost $": max(costs) if costs else None,
        f"runs within ${limits.cost_usd:.2f}": ratio(sum(c <= limits.cost_usd for c in costs),
                                                    len(costs)),
        "mean time s": mean(times), "max time s": max(times) if times else None,
        f"runs within {limits.seconds} s": ratio(sum(t <= limits.seconds for t in times),
                                                 len(times)),
        "runs stopped by a limit": sum(1 for r in rows if r["stop"]),
    }
    return component("whole pipeline", "One request end to end: research loop, writer, "
                     "finalize; hard stops on calls, cost and time.", metrics, rows)
