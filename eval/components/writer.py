"""writer (LLM + 2 tools): is the dossier valid, faithful to the research,
honest about missing data, and are the cited case studies the right ones?

Measured on the collected runs: report.md against the research facts of
trace.json (with their SourceVerifier status), the writer's tool calls
(calls.json) and the relevant case studies labelled in companies.json.
"""
from dossier_agent.format_check import MAX_WORDS, check_dossier_format
from dossier_agent.verification import claim_coverage

from .common import (FACT_SECTIONS, RESEARCH_TO_DOSSIER, component, dossier_sections,
                     extract_urls, is_pending, prf, ratio, strip_urls)

FAITHFUL_OVERLAP = 0.5      # share of the bullet's key words found in the research claim


def norm_url(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/").lower()


def research_index(run) -> tuple[dict, set]:
    """normalized URL -> research facts with that URL (all iterations), and every
    URL the research mentions."""
    by_url, urls = {}, set()
    for iteration in run.iterations:
        urls |= {norm_url(u) for u in extract_urls(iteration.get("research", ""))}
        for fact in iteration.get("facts") or []:
            for key in {norm_url(fact.get("url")), norm_url(fact.get("final_url"))} - {""}:
                by_url.setdefault(key, []).append(fact)
                urls.add(key)
    return by_url, urls


def classify_bullet(line: str, by_url: dict) -> str:
    """faithful | hypothesis grounded | hypothesis ungrounded | unverified source |
    rewritten | no research fact"""
    urls = [norm_url(u) for u in extract_urls(line)]
    facts = [f for u in urls for f in by_url.get(u, [])]
    if line.startswith("- Hypothesis:"):
        return ("hypothesis grounded" if any(f.get("status") == "supported" for f in facts)
                else "hypothesis ungrounded")
    if not facts:
        return "no research fact"
    supported = [f for f in facts if f.get("status") == "supported"]
    if not supported:
        return "unverified source"
    text = strip_urls(line)
    best = max(claim_coverage(text, f.get("claim", "")) for f in supported)
    return "faithful" if best >= FAITHFUL_OVERLAP else "rewritten"


def final_sections_with_facts(run) -> set:
    if not run.iterations:
        return set()
    facts = run.iterations[-1].get("facts") or []
    return {RESEARCH_TO_DOSSIER.get(str(f.get("section", "")).lower())
            for f in facts if f.get("status") == "supported"} & set(FACT_SECTIONS)


def evaluate(runs) -> dict:
    rows, bullets_total, bullet_kinds = [], 0, {}
    format_ok, provenance_in, provenance_all, first_try = [], 0, 0, []
    honesty = {"ok": 0, "facts without support": 0, "dropped": 0}
    case_tp = case_fp = case_fn = 0
    abstain_ok, case_provenance = [], []
    for run in runs:
        if not run.report:
            rows.append({"run": run.id, "format ok": False, "note": "no dossier"})
            format_ok.append(False)
            continue
        seller = run.data.get("seller") or "Metacortex"
        valid = check_dossier_format(run.report, angle_section=f"{seller} angle")["success"]
        format_ok.append(valid)
        body = run.report.split("\n## Sources")[0]
        words = len(body.split())
        by_url, research_urls = research_index(run)
        case_urls = {norm_url(c.get("url")) for c in run.data.get("seller_cases") or []}
        urls = [norm_url(u) for u in extract_urls(body)]
        inside = sum(u in research_urls or u in case_urls or "example.com" in u for u in urls)
        provenance_in += inside
        provenance_all += len(urls)

        sections = dossier_sections(run.report)
        kinds = {}
        for name in FACT_SECTIONS:
            for line in sections.get(name, []):
                if is_pending(line):
                    continue
                kind = classify_bullet(line, by_url)
                kinds[kind] = kinds.get(kind, 0) + 1
                bullet_kinds[kind] = bullet_kinds.get(kind, 0) + 1
                bullets_total += 1

        with_facts = final_sections_with_facts(run)
        dropped, unsupported = [], []
        for name in FACT_SECTIONS:
            lines = [l for l in sections.get(name, []) if not is_pending(l)]
            # hypotheses rest on facts of other sections (scored above), not on this one
            facts_only = [l for l in lines if not l.startswith("- Hypothesis:")]
            if name in with_facts:
                ok = bool(lines)
            else:
                ok = not facts_only
            if ok:
                honesty["ok"] += 1
            elif name in with_facts:
                honesty["dropped"] += 1
                dropped.append(name)
            else:
                honesty["facts without support"] += 1
                unsupported.append(name)

        cited = [c.get("id") for c in run.data.get("seller_cases") or []]
        relevant = set(run.spec.get("relevant_cases") or [])
        loaded = {i for c in run.calls.get("calls", []) if c.get("type") == "response"
                  and c.get("name") == "load_seller_cases" for i in c.get("case_ids", [])}
        if run.calls:
            case_provenance.append(set(cited) <= loaded)
        if run.kind == "fictional" or not relevant:
            abstain_ok.append(not cited)
        else:
            case_tp += len(set(cited) & relevant)
            case_fp += len(set(cited) - relevant)
            case_fn += len(relevant - set(cited))
        checks = [c for c in run.calls.get("calls", []) if c.get("type") == "response"
                  and c.get("name") == "check_dossier_format"]
        if checks:
            first_try.append(bool(checks[0].get("success")))

        rows.append({
            "run": run.id, "format ok": valid, "words": words,
            "URLs from research/cases": f"{inside}/{len(urls)}",
            "faithful bullets": f"{kinds.get('faithful', 0)}/"
                                f"{sum(v for k, v in kinds.items() if not k.startswith('hyp'))}",
            "other bullets": ", ".join(f"{k} {v}" for k, v in kinds.items() if k != "faithful"),
            "sections dropped / unsupported": ", ".join(dropped + [f"{u}!" for u in unsupported])
                                              or "—",
            "cases cited (relevant)": ", ".join(cited) + (f" ({', '.join(sorted(relevant))})"
                                                        if relevant else " (none fits)"),
            "format checks (1st ok)": f"{len(checks)} ({checks[0].get('success')})" if checks
                                      else "0",
        })

    fact_bullets = sum(v for k, v in bullet_kinds.items() if not k.startswith("hypothesis"))
    hypotheses = sum(v for k, v in bullet_kinds.items() if k.startswith("hypothesis"))
    cases = prf(case_tp, case_fp, case_fn)
    sections_total = sum(honesty.values())
    metrics = {
        "runs with a dossier": sum(1 for r in runs if r.report),
        "format valid": ratio(sum(format_ok), len(format_ok)),
        "format valid at the first check_dossier_format call": ratio(sum(first_try),
                                                                     len(first_try)),
        f"within {MAX_WORDS} words": ratio(sum(1 for r in rows if (r.get("words") or 0)
                                               <= MAX_WORDS and r.get("words")), len(rows)),
        "URLs that come from the research or the case list": ratio(provenance_in,
                                                                   provenance_all),
        "faithful fact bullets (match a supported research fact)":
            ratio(bullet_kinds.get("faithful", 0), fact_bullets),
        "bullets citing an unverified source": ratio(bullet_kinds.get("unverified source", 0),
                                                     fact_bullets),
        "hypotheses based on a supported fact": ratio(bullet_kinds.get("hypothesis grounded",
                                                                       0), hypotheses),
        "sections honest about missing data (content ⇔ supported research)":
            ratio(honesty["ok"], sections_total),
        "sections with facts but no supported research": honesty["facts without support"],
        "sections left [Pending] although the research had facts": honesty["dropped"],
        "cited case studies: precision (relevant / cited)": cases["precision"],
        "cited case studies: recall (cited / relevant)": cases["recall"],
        "cited case studies all returned by load_seller_cases": ratio(sum(case_provenance),
                                                                      len(case_provenance)),
        "no case cited when none fits (fictional company)": ratio(sum(abstain_ok),
                                                                  len(abstain_ok)),
    }
    notes = [f"A fact bullet is faithful when at least {FAITHFUL_OVERLAP:.0%} of its key words "
             "are in a supported research fact with the same URL; 'rewritten' means the URL is "
             "right but the wording moved away from the verified claim.",
             "'!' marks a section that has facts in the dossier but none supported in the "
             "final research."]
    return component("writer", "Writes the dossier from the verified research; picks case "
                     "studies with load_seller_cases and checks itself with "
                     "check_dossier_format.", metrics, rows, notes,
                     ["run", "format ok", "words", "URLs from research/cases", "faithful bullets",
                      "other bullets", "sections dropped / unsupported",
                      "cases cited (relevant)", "format checks (1st ok)"])
