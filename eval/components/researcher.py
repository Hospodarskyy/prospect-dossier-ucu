"""researcher (LLM + Google Search): how well its facts hold up.

Measured on the collected runs, from trace.json: every fact the researcher
wrote has a status from SourceVerifier (quote found on the cited page or not).
"Checkable" facts exclude pages that could not be fetched (bot protection,
timeouts): that is not the researcher's fault.
"""
import re
from collections import Counter
from datetime import date

from .common import FACT_SECTIONS, RESEARCH_TO_DOSSIER, component, mean, ratio

FRESH_DAYS = 90


def _section(fact: dict) -> str:
    return RESEARCH_TO_DOSSIER.get(str(fact.get("section", "")).strip().lower(), "other")


def fact_stats(iteration: dict) -> dict:
    facts = [f for f in iteration.get("facts") or [] if isinstance(f, dict)]
    status = Counter(f.get("status") for f in facts)
    checkable = len(facts) - status["unreachable"]
    supported = [f for f in facts if f.get("status") == "supported"]
    return {
        "facts": len(facts),
        "checkable": checkable,
        "supported": len(supported),
        "weak": sum(1 for f in supported if f.get("weak_support")),
        "not_found": status["not_found"],
        "dead_link": status["dead_link"],
        "no_quote_or_url": status["missing_quote"] + status["missing_source"],
        "unreachable": status["unreachable"],
        "sections": {_section(f) for f in supported} & set(FACT_SECTIONS),
        "supported_facts": supported,
    }


def _searches_reported(research: str) -> int:
    match = re.search(r"Searches performed:\s*(\d+)", research or "")
    return int(match.group(1)) if match else 0


def news_stats(supported: list[dict], run_date: str) -> dict:
    news = [f for f in supported if _section(f) == "Recent news"]
    dated, fresh, verified = 0, 0, 0
    for fact in news:
        try:
            when = date.fromisoformat(str(fact.get("date")))
        except ValueError:
            continue
        dated += 1
        verified += fact.get("date_check") in ("exact", "month")
        try:
            fresh += (date.fromisoformat(run_date) - when).days <= FRESH_DAYS
        except ValueError:
            pass
    return {"news": len(news), "dated": dated, "fresh": fresh, "date_on_page": verified}


def evaluate(runs) -> dict:
    rows, real = [], []
    pooled = Counter()
    first_pooled = Counter()
    invented_fictional = 0
    for run in runs:
        if not run.iterations:
            rows.append({"run": run.id, "note": "no trace (run failed before research)"})
            continue
        first, last = fact_stats(run.iterations[0]), fact_stats(run.iterations[-1])
        news = news_stats(last["supported_facts"], run.run_date)
        pending = (run.iterations[-1].get("verification_counts") or {}).get("pending", 0)
        row = {
            "run": run.id,
            "iterations": len(run.iterations),
            "facts (final)": last["facts"],
            "grounded 1st": ratio(first["supported"], first["checkable"]),
            "grounded final": ratio(last["supported"], last["checkable"]),
            "weak share": ratio(last["weak"], last["supported"]),
            "misquoted": last["not_found"],
            "dead links": last["dead_link"],
            "unreachable": last["unreachable"],
            "sections covered": f"{len(last['sections'])}/{len(FACT_SECTIONS)}",
            "pending items": pending,
            "news (fresh/dated)": f"{news['fresh']}/{news['dated']}",
            "searches reported": sum(_searches_reported(i.get("research", ""))
                                     for i in run.iterations),
        }
        rows.append(row)
        if run.kind == "fictional":
            invented_fictional += sum(fact_stats(i)["facts"] for i in run.iterations)
            continue
        real.append((run, last, news))
        for key in ("checkable", "supported", "weak", "not_found", "dead_link", "unreachable",
                    "facts"):
            pooled[key] += last[key]
            first_pooled[key] += first[key]
        pooled["news_dated"] += news["dated"]
        pooled["news_fresh"] += news["fresh"]
        pooled["news_date_on_page"] += news["date_on_page"]

    metrics = {
        "real-company runs": len(real),
        "grounded rate, 1st iteration (supported / checkable)":
            ratio(first_pooled["supported"], first_pooled["checkable"]),
        "grounded rate, final iteration": ratio(pooled["supported"], pooled["checkable"]),
        "weak support (share of supported facts)": ratio(pooled["weak"], pooled["supported"]),
        "misquote rate (quote not on the page)": ratio(pooled["not_found"], pooled["checkable"]),
        "dead-link rate": ratio(pooled["dead_link"], pooled["checkable"]),
        "unreachable pages (excluded above)": ratio(pooled["unreachable"], pooled["facts"]),
        "section coverage (mean share of the 5 fact sections with a supported fact)":
            mean(len(last["sections"]) / len(FACT_SECTIONS) for _, last, _ in real),
        "runs with at least one supported recent news item":
            ratio(sum(1 for _, _, n in real if n["news"]), len(real)),
        "dated news within 90 days": ratio(pooled["news_fresh"], pooled["news_dated"]),
        "news dates found on the page": ratio(pooled["news_date_on_page"], pooled["news_dated"]),
        "fictional company: facts with a source (target 0)": invented_fictional,
    }
    notes = [
        "Grounded = SourceVerifier found the quote on the cited page; it does not prove the "
        "claim says no more than the quote (that is the weak-support flag and the judge).",
        "1st vs final iteration shows what the judge loop adds.",
    ]
    return component("researcher", "Searches the web (Google Search grounding) and writes "
                     "facts with a URL and a verbatim quote, or [Pending].",
                     metrics, rows, notes,
                     ["run", "iterations", "facts (final)", "grounded 1st", "grounded final",
                      "weak share", "misquoted", "dead links", "unreachable", "sections covered",
                      "pending items", "news (fresh/dated)", "searches reported"])
