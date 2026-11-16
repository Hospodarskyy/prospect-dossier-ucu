import json
import re

from .format_check import (
    FACT_SECTION_ORDER, FACT_SECTIONS, HYPOTHESIS_PREFIX, PENDING_PREFIX,
    SOURCES_SECTION, URL_RE, _split_sections, extract_urls,
)
from .memory import extract_facts
from .schemas import RunResult
from .seller_cases import angle_section
from .storage import Storage, get_storage

AGENT_NAME = "prospect-dossier"     # the "agent" field of result.json


UNSOURCED_STATUSES = ("missing_source", "missing_quote", "not_found", "dead_link")

MIN_HYPOTHESES = 3

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_URL_AT_END_RE = re.compile(r"\s*\((https?://\S+?)\)\s*$")
_BASED_ON_RE = re.compile(r"\s*\(based on:.*\)\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Judge feedback
# --------------------------------------------------------------------------
def parse_feedback(feedback) -> dict:
    """state["judge_feedback"] may be a dict or a JSON string; {} if unusable."""
    if isinstance(feedback, str):
        try:
            feedback = json.loads(feedback)
        except json.JSONDecodeError:
            return {}
    return feedback if isinstance(feedback, dict) else {}


def judge_status(feedback) -> str:
    """'pass' | 'fail' | 'unknown'."""
    value = parse_feedback(feedback).get("status")
    return value if value in ("pass", "fail") else "unknown"


# --------------------------------------------------------------------------
# Data extracted from the dossier Markdown
# --------------------------------------------------------------------------
def _bullets(dossier_md: str, section: str) -> list[str]:
    _, sections = _split_sections(dossier_md or "")
    for name, body in sections:
        if name == section:
            return [l.strip() for l in body.splitlines() if l.strip().startswith("- ")]
    return []


def extract_news(dossier_md: str) -> list[dict]:
    return [
        {"date": f["date"], "title": f["text"], "url": f["url"]}
        for f in extract_facts(dossier_md) if f["section"] == "Recent news"
    ]


def extract_pains(dossier_md: str) -> list[dict]:
    """Hypotheses in Likely pains: '- Hypothesis: <text> (based on: ...) (<URL>)'."""
    pains = []
    for line in _bullets(dossier_md, "Likely pains"):
        if not line.startswith(HYPOTHESIS_PREFIX):
            continue
        text = line[len(HYPOTHESIS_PREFIX):]
        m = _URL_AT_END_RE.search(text)
        url = m.group(1) if m else None
        if m:
            text = text[:m.start()]
        text = _BASED_ON_RE.sub("", text).strip()
        pains.append({"hypothesis": text, "evidence_url": url})
    return pains


def extract_seller_cases(dossier_md: str, case_studies: list[dict], *,
                         angle_section: str) -> list[dict]:
    """Case studies cited (by URL) in the angle section, in file order."""
    _, sections = _split_sections(dossier_md or "")
    cited = set()
    for name, body in sections:
        if name == angle_section:
            cited |= extract_urls(body)
    return [
        {"id": c.get("id"), "title": c.get("title"), "url": c["url"]}
        for c in case_studies if c.get("url") in cited
    ]


def pending_sections(dossier_md: str) -> list[str]:
    """Fact sections whose only content is '- [Pending]'."""
    _, sections = _split_sections(dossier_md or "")
    result = []
    for name, body in sections:
        if name not in FACT_SECTIONS:
            continue
        bullets = [l.strip() for l in body.splitlines() if l.strip().startswith("- ")]
        if bullets and all(b.startswith(PENDING_PREFIX) for b in bullets):
            result.append(name)
    return [s for s in FACT_SECTION_ORDER if s in result]


def replace_urls(text: str, mapping: dict | None) -> str:
    """Replace redirect links with real page URLs ({old: new}). Longer keys
    first, so a URL that is a prefix of another one is never half-replaced."""
    text = text or ""
    if not isinstance(mapping, dict):
        return text
    for old in sorted(mapping, key=len, reverse=True):
        new = mapping[old]
        if isinstance(old, str) and isinstance(new, str) and old and new:
            text = text.replace(old, new)
    return text


def add_sources(dossier_md: str) -> str:
    """report.md = dossier + "## Sources": every distinct URL of the dossier in
    order of first appearance. A Sources section written by the model is
    replaced, so the list always matches the dossier."""
    lines, kept, skipping = (dossier_md or "").splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            skipping = line[3:].strip() == SOURCES_SECTION
        if not skipping:
            kept.append(line)
    body = "\n".join(kept).rstrip()
    urls = []
    for raw in URL_RE.findall(body):
        url = raw.rstrip(").,;]\"'")
        if url not in urls:
            urls.append(url)
    sources = "\n".join(f"- {u}" for u in urls) if urls else "- [Pending]"
    return f"{body}\n\n## {SOURCES_SECTION}\n{sources}\n"


def _clean_url(url: str | None) -> str | None:
    return url.rstrip(").,;]\"'") if isinstance(url, str) else None


def unsourced_count(counts) -> int | None:
    """Research claims the SourceVerifier did not confirm (last iteration).
    None when there are no counts (verification failed or research unparsable)."""
    if not isinstance(counts, dict):
        return None
    return sum(int(counts.get(s, 0)) for s in UNSOURCED_STATUSES)


# --------------------------------------------------------------------------
# result.json
# --------------------------------------------------------------------------
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _first_url(text: str) -> str:
    urls = URL_RE.findall(text or "")
    return _clean_url(urls[0]) if urls else ""


def _item(id_: str, question: str, source_ref: str = "") -> dict:
    return {"id": id_, "question": question, "source_ref": source_ref}


def build_pending_human(feedback, dossier_md: str) -> list[dict]:
    """What a person should check by hand, as {id, question, source_ref}:
    judge problems when the judge did not pass, plus sections with no data
    and too few pain hypotheses (always)."""
    items = []
    fb = parse_feedback(feedback)
    if judge_status(fb) != "pass":
        items += [_item(f"missing-section-{_slug(s)}", f"Missing section: {s}", s)
                  for s in fb.get("missing_sections") or []]
        items += [_item(f"unsourced-{i}", f"Unsourced claim: {c}", _first_url(c))
                  for i, c in enumerate(fb.get("unsourced_claims") or [], 1)]
        items += [_item(f"stale-news-{i}", f"Stale news: {n}", _first_url(n))
                  for i, n in enumerate(fb.get("stale_news") or [], 1)]
        if not items:
            summary = (fb.get("summary") or "").strip()
            items.append(_item("judge-not-passed",
                               f"Judge did not pass the research: {summary}" if summary
                               else "Judge did not pass the research."))
    empty = pending_sections(dossier_md)
    items += [_item(f"no-data-{_slug(s)}", f"No data: {s}", s) for s in empty]
    n = len(extract_pains(dossier_md))
    if "Likely pains" not in empty and n < MIN_HYPOTHESES:
        items.append(_item("few-pain-hypotheses",
                           f"Few pain hypotheses: {n} (target {MIN_HYPOTHESES}-5)",
                           "Likely pains"))
    return items


def build_data(*, company: str, domain: str, iterations: int, judge_feedback,
               dossier_md: str, verification_counts, case_studies: list[dict],
               seller: str, previous_dossier_date: str | None) -> dict:
    return {
        "company": company,
        "domain": domain,
        "iterations": iterations,
        "judge_status": "pass" if judge_status(judge_feedback) == "pass" else "fail",
        "facts_count": len(extract_facts(dossier_md)),
        "unsourced_count": unsourced_count(verification_counts),
        "news": extract_news(dossier_md),
        "pains": extract_pains(dossier_md),
        "seller": seller,
        "seller_cases": extract_seller_cases(dossier_md, case_studies,
                                             angle_section=angle_section(seller)),
        "previous_dossier_date": previous_dossier_date or None,
    }


def build_result(*, agent: str, run_id: str, trigger: str, started_at: str,
                 status: str, pending_human: list[dict], errors: list[dict],
                 usage: dict | None, data: dict | None) -> dict:
    """The result.json envelope, validated by RunResult (raises
    pydantic.ValidationError if it does not match the spec). The service
    uses it too (status 'failed', data None)."""
    return RunResult(
        agent=agent, run_id=run_id, status=status, trigger=trigger,
        started_at=started_at, items_processed=1, pending_human=pending_human,
        errors=errors, usage=usage, data=data,
    ).model_dump(mode="json")


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def check_run_id(run_id: str) -> str:
    """run_id becomes a folder name: letters, digits, '_', '.', '-' only."""
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id) or ".." in run_id:
        raise ValueError(f"invalid run_id: {run_id!r}")
    return run_id


def outbox_prefix(started_at: str, run_id: str) -> str:
    date = started_at[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"invalid started_at: {started_at!r}")
    return f"outbox/{date}/{check_run_id(run_id)}"


def write_outbox(prefix: str, report_md: str | None, result: dict,
                 storage: Storage | None = None, extra_files: dict[str, str] | None = None) -> None:
    """report.md (if there is a dossier), extra files (e.g. trace.json) and
    result.json. result.json goes last, so its presence means the run output
    is complete."""
    s = storage or get_storage()
    if report_md:
        s.write_text(f"{prefix}/report.md", report_md)
    for name, text in (extra_files or {}).items():
        s.write_text(f"{prefix}/{name}", text)
    s.write_text(f"{prefix}/result.json", json.dumps(result, indent=2, ensure_ascii=False))
