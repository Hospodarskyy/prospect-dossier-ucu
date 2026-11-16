"""Memory and "What changed": is the previous dossier loaded, compared and saved?

First request for a domain: no previous dossier, "What changed" is [Pending].
Repeated request (seed memory in eval/data/seed): the previous date is loaded,
"What changed" lists changes as "<what>: <before> -> <now>" or says
"No material changes since <date>". Every finished run saves its facts as the
new memory (memory.json of the run has the run's run_id).
"""
from .common import component, dossier_sections, is_pending, ratio


def check(run) -> dict:
    sections = dossier_sections(run.report or "")
    bullets = sections.get("What changed", [])
    previous = run.data.get("previous_dossier_date") or ""
    if not run.report:
        return {"run": run.id, "repeat": bool(run.spec.get("seed_memory")), "ok": False,
                "note": "no dossier"}
    if run.spec.get("seed_memory"):
        loaded = bool(previous)
        well_formed = bool(bullets) and all(
            "->" in b or b.startswith(f"- No material changes since {previous}") for b in bullets)
        ok = loaded and well_formed and not all(is_pending(b) for b in bullets)
    else:
        loaded = previous == ""
        well_formed = bool(bullets) and all(is_pending(b) for b in bullets)
        ok = loaded and well_formed
    saved = bool(run.memory) and run.memory.get("run_id") == run.result.get("run_id")
    return {"run": run.id, "repeat": bool(run.spec.get("seed_memory")),
            "previous dossier": previous or "none", "previous loaded correctly": loaded,
            "What changed": " / ".join(b[2:][:90] for b in bullets) or "missing",
            "well formed": well_formed, "ok": ok, "memory saved": saved}


def evaluate(runs) -> dict:
    rows = [check(r) for r in runs]
    repeat = [r for r in rows if r["repeat"]]
    first = [r for r in rows if not r["repeat"]]
    finished = [r for r, run in zip(rows, runs) if run.result.get("status") in ("ok", "partial")]
    metrics = {
        "first requests: What changed correctly [Pending]": ratio(sum(r["ok"] for r in first),
                                                                  len(first)),
        "repeated requests: previous dossier loaded and changes reported":
            ratio(sum(r["ok"] for r in repeat), len(repeat)),
        "finished runs that saved their memory": ratio(sum(r.get("memory saved", False)
                                                           for r in finished), len(finished)),
    }
    notes = ["Only one repeated request is in the set (Plausible, memory from 2026-11-12); "
             "whether the listed changes are true is checked by the judge loop, not here."]
    return component("memory / What changed", "Loads the previous dossier of the domain, "
                     "lets the writer compare, and saves the new facts as memory.",
                     metrics, rows, notes,
                     ["run", "repeat", "previous dossier", "What changed", "well formed", "ok",
                      "memory saved"])
