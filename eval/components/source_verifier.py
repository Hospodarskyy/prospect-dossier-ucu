"""SourceVerifier (script, no LLM): does it judge quotes correctly?

Runs the real verify_fact on labelled cases with saved page texts
(eval/data/verifier/): synthetic cases built from the pages of the eval runs
(label known by construction, see eval/build_verifier_set.py) and real facts
of the eval runs labelled by hand (eval/data/verifier_manual.jsonl).
"""
import json
from collections import defaultdict

from dossier_agent.verification import Fact, FetchResult, verify_fact

from .common import DATA_DIR, component, prf, ratio, read_json

VERIFIER_DIR = DATA_DIR / "verifier"


def _jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_cases() -> list[dict]:
    return _jsonl(VERIFIER_DIR / "cases.jsonl") + _jsonl(DATA_DIR / "verifier_manual.jsonl")


def run_case(case: dict, page: dict) -> dict:
    fact = Fact(kind="fact", section="Snapshot", claim=case["claim"], url=page["url"],
                quote=case["quote"], date=case.get("date"))
    got = verify_fact(fact, FetchResult(ok=True, final_url=page["url"], text=page["text"],
                                        status_code=200))
    status_ok = got["status"] == case["expect_status"]
    weak_ok = case.get("expect_weak") is None or got["weak_support"] == case["expect_weak"]
    date_ok = case.get("expect_date") is None or got["date_check"] == case["expect_date"]
    return {"id": case["id"], "variant": case["variant"], "source": case.get("source"),
            "expect": case["expect_status"] + (" + weak" if case.get("expect_weak") else ""),
            "got": got["status"] + (" + weak" if got["weak_support"] else ""),
            "expect_date": case.get("expect_date"), "got_date": got["date_check"],
            "status_ok": status_ok, "weak_ok": weak_ok, "date_ok": date_ok,
            "ok": status_ok and weak_ok and date_ok,
            "pred_supported": got["status"] == "supported", "pred_weak": got["weak_support"],
            "exp_supported": case["expect_status"] == "supported",
            "exp_weak": case.get("expect_weak"), "detail": got["detail"]}


def evaluate(runs=None) -> dict:
    results = []
    for case in load_cases():
        page = read_json(VERIFIER_DIR / "pages" / f"{case['page']}.json")
        if page:
            results.append(run_case(case, page))
    if not results:
        return component("SourceVerifier", "no labelled cases: run python -m "
                         "eval.build_verifier_set", {})

    def weak_prf(rows):
        rows = [r for r in rows if r["exp_weak"] is not None and r["pred_supported"]]
        return prf(sum(r["exp_weak"] and r["pred_weak"] for r in rows),
                   sum(r["pred_weak"] and not r["exp_weak"] for r in rows),
                   sum(r["exp_weak"] and not r["pred_weak"] for r in rows))

    sup = [(r["exp_supported"], r["pred_supported"]) for r in results]
    supported = prf(sum(e and p for e, p in sup), sum(p and not e for e, p in sup),
                    sum(e and not p for e, p in sup))
    manual = [r for r in results if r["source"] == "manual"]
    weak = weak_prf([r for r in results if r["source"] != "manual"])
    weak_real = weak_prf(manual)
    dates = [r for r in results if r["expect_date"] is not None]

    metrics = {
        "cases (synthetic + hand-labelled)": f"{len(results) - len(manual)} + {len(manual)}",
        "'supported' precision": supported["precision"],
        "'supported' recall": supported["recall"],
        "'supported' F1": supported["f1"],
        "weak-support flag precision (synthetic)": weak["precision"],
        "weak-support flag recall (synthetic)": weak["recall"],
        "weak-support flag F1 (synthetic)": weak["f1"],
        "date check accuracy": ratio(sum(r["date_ok"] for r in dates), len(dates)),
        "real facts: fully correct": ratio(sum(r["ok"] for r in manual), len(manual)),
        "real facts: weak-support flag precision": weak_real["precision"],
        "real facts: weak-support flag recall": weak_real["recall"],
    }
    by_variant = defaultdict(list)
    for r in results:
        by_variant[r["variant"]].append(r)
    rows = [{"variant": v, "cases": len(rs), "correct": sum(r["ok"] for r in rs),
             "accuracy": ratio(sum(r["ok"] for r in rs), len(rs)),
             "expected": rs[0]["expect"], "typical result": _typical(rs)}
            for v, rs in by_variant.items()]
    notes = ["Positive class of 'supported': the quote really is on the page. Weak-support "
             "flag: the claim says more than the quote (counted on cases the verifier "
             "marked supported)."]
    misses = [r for r in manual if not r["ok"]]
    notes += [f"hand-labelled miss: {r['id']}: expected {r['expect']}, got {r['got']} "
              f"({r['detail']})" for r in misses]
    return component("SourceVerifier", "Fetches every cited page and checks that the quote "
                     "is on it (and the date); flags claims that say more than the quote.",
                     metrics, rows, notes,
                     ["variant", "cases", "correct", "accuracy", "expected", "typical result"])


def _typical(rows: list[dict]) -> str:
    counts = defaultdict(int)
    for r in rows:
        counts[r["got"] + (f" / date {r['got_date']}" if r["expect_date"] else "")] += 1
    return ", ".join(f"{k} ×{n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
