"""init_state: parsing the JSON request (company, domain, context).

Labelled set eval/data/requests.jsonl: valid requests with the expected
normalized fields, and invalid ones with the expected error. No model call:
this component is deterministic, so the metric is plain accuracy.
"""
import json

from dossier_agent.request import parse_request

from .common import DATA_DIR, component, ratio


def load_cases() -> list[dict]:
    lines = (DATA_DIR / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def check(case: dict) -> dict:
    expected = case["expected"]
    try:
        got, error = parse_request(case["input"]), None
    except ValueError as exc:
        got, error = None, str(exc)
    if "error" in expected:
        ok = error is not None and expected["error"] in error
    else:
        ok = got == expected
    return {"case": case["name"], "expected": "error" if "error" in expected else "parsed",
            "ok": ok, "got": error or json.dumps(got, ensure_ascii=False)}


def evaluate(runs=None) -> dict:
    rows = [check(c) for c in load_cases()]
    valid = [r for r in rows if r["expected"] == "parsed"]
    invalid = [r for r in rows if r["expected"] == "error"]
    metrics = {
        "cases": len(rows),
        "accuracy": ratio(sum(r["ok"] for r in rows), len(rows)),
        "valid requests parsed correctly": ratio(sum(r["ok"] for r in valid), len(valid)),
        "invalid requests rejected with the right error": ratio(sum(r["ok"] for r in invalid),
                                                               len(invalid)),
    }
    notes = ["Deterministic code: this is a labelled test set more than a quality measure; "
             "it shows the input contract the rest of the pipeline relies on."]
    return component("init_state: request parsing",
                     "Turns the JSON request into company, domain (normalized) and context; "
                     "rejects bad input before any model call.",
                     metrics, rows, notes, ["case", "expected", "ok", "got"])
