"""load_seller_cases (tool, script): does it rank the fitting case study first?

select_candidates returns up to 5 of the seller's 6 case studies, best match
first. With 6 cases precision@5 says nothing, so the metrics are hit@1 (the
first case fits) and MRR (1 / rank of the first fitting case). Two inputs:
hand-made writer-like profiles (eval/data/case_profiles.json), and the real
arguments the writer passed in the eval runs (calls.json).
"""
from dossier_agent.seller_cases import parse_seller_cases, select_candidates

from .common import DATA_DIR, ROOT, component, mean, ratio, read_json

CASES_FILE = ROOT / "demo-data" / "config" / "seller_cases.md"


def rank_of_first(ranking: list[str], relevant: set) -> int | None:
    return next((i for i, cid in enumerate(ranking, 1) if cid in relevant), None)


def score(name: str, source: str, industry, tech, relevant: set, cases: list[dict]) -> dict:
    ranking = [c["id"] for c in select_candidates(cases, industry, tech)]
    rank = rank_of_first(ranking, relevant)
    return {"input": name, "source": source, "industry": industry,
            "tech": ", ".join(map(str, tech or [])), "relevant": ", ".join(sorted(relevant)),
            "ranking": " ".join(ranking), "rank": rank, "hit@1": rank == 1,
            "rr": round(1 / rank, 3) if rank else 0.0}


def evaluate(runs) -> dict:
    cases = parse_seller_cases(CASES_FILE.read_text(encoding="utf-8"))
    rows = [score(p["name"], "profile", p["industry"], p["tech"], set(p["relevant"]), cases)
            for p in read_json(DATA_DIR / "case_profiles.json")["profiles"]]
    for run in runs:
        relevant = set(run.spec.get("relevant_cases") or [])
        calls = [c for c in run.calls.get("calls", []) if c.get("type") == "call"
                 and c.get("name") == "load_seller_cases"]
        if relevant and calls:
            args = calls[0].get("args") or {}
            rows.append(score(run.id, "eval run", args.get("industry"), args.get("tech"),
                              relevant, cases))
    metrics = {}
    for source in ("profile", "eval run"):
        part = [r for r in rows if r["source"] == source]
        metrics[f"{source}s: inputs"] = len(part)
        metrics[f"{source}s: hit@1"] = ratio(sum(r["hit@1"] for r in part), len(part))
        metrics[f"{source}s: MRR"] = mean(r["rr"] for r in part)
    notes = ["Scoring is keyword-based: +2 for the same industry, +1 per technology or "
             "problem word that matches. Synonyms (Retail vs E-commerce, Healthcare vs "
             "HealthTech) are not understood."]
    return component("load_seller_cases", "Returns up to 5 of the seller's case studies that "
                     "best match the industry and technologies the writer passes.",
                     metrics, rows, notes,
                     ["input", "source", "industry", "tech", "relevant", "ranking", "rank"])
