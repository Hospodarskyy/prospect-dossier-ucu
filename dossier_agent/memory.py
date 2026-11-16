import json
import logging
import re
from datetime import date, datetime, timezone

from .format_check import (
    FACT_SECTION_ORDER, FACT_SECTIONS, HYPOTHESIS_PREFIX, PENDING_PREFIX, _split_sections,
)
from .request import normalize_domain
from .storage import Storage, get_storage
from .verification import parse_research

log = logging.getLogger(__name__)

DOSSIER_DIR = "state/dossiers"
SECTION_ORDER = FACT_SECTION_ORDER

_URL_AT_END_RE = re.compile(r"\s*\((https?://\S+?)\)\s*$")
_DATE_RE = re.compile(r"\s*\(date:\s*([^)]*)\)")


def dossier_key(domain: str) -> str:
    return f"{DOSSIER_DIR}/{normalize_domain(domain)}.json"


def extract_facts(dossier_md: str) -> list[dict]:
    """Sourced bullets of the fact sections, in dossier order.

    "- <claim> (date: YYYY-MM-DD) (<URL>)" -> {section, text, url, date}.
    [Pending] bullets, hypotheses and bullets without a trailing URL are skipped.
    """
    _, sections = _split_sections(dossier_md or "")
    facts = []
    for section, body in sections:
        if section not in FACT_SECTIONS:
            continue
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("- ") or line.startswith((PENDING_PREFIX, HYPOTHESIS_PREFIX)):
                continue
            m = _URL_AT_END_RE.search(line)
            if not m:
                continue
            rest = line[2:m.start()]
            d = _DATE_RE.search(rest)
            date = d.group(1).strip() if d else None
            if d:
                rest = rest[:d.start()] + rest[d.end():]
            facts.append({
                "section": section,
                "text": rest.strip(),
                "url": m.group(1),
                "date": date or None,
            })
    return facts


def build_record(domain: str, run_id: str, judge_status: str, dossier_md: str,
                 saved_at: datetime | None = None) -> dict:
    saved_at = saved_at or datetime.now(timezone.utc)
    return {
        "domain": normalize_domain(domain),
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "run_id": run_id,
        "judge_status": judge_status,
        "facts": extract_facts(dossier_md),
    }


def _valid_record(data) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("saved_at"), str)
        and isinstance(data.get("facts"), list)
        and all(isinstance(f, dict) and isinstance(f.get("text"), str)
                for f in data["facts"])
    )


def load_previous_dossier(domain: str, storage: Storage | None = None) -> dict | None:
    """The saved record for this domain, or None if there is none or it is
    corrupt (a corrupt file is logged and treated as missing). Storage errors
    (network, permissions) are raised: they are technical failures of the run."""
    key = dossier_key(domain)
    text = (storage or get_storage()).read_text(key)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("Corrupt dossier file %s: %s", key, exc)
        return None
    if not _valid_record(data):
        log.warning("Dossier file %s has an unexpected structure", key)
        return None
    return data


def save_dossier(domain: str, record: dict, storage: Storage | None = None) -> str:
    """Overwrite state/dossiers/<domain>.json. Returns the storage key."""
    key = dossier_key(domain)
    text = json.dumps(record, indent=2, ensure_ascii=False)
    (storage or get_storage()).write_text(key, text)
    return key


def format_prior_knowledge(record: dict | None) -> str:
    """Compact text for the writer's PREVIOUS DOSSIER block ("" if no record)."""
    if not record:
        return ""
    date = record["saved_at"][:10]
    status = record.get("judge_status") or "unknown"
    lines = [f"Previous dossier from {date} (judge status: {status})."]
    for section in SECTION_ORDER:
        facts = [f for f in record["facts"] if f.get("section") == section]
        if not facts:
            continue
        lines.append(f"## {section}")
        for f in facts:
            line = f"- {f['text']}"
            if f.get("date"):
                line += f" (date: {f['date']})"
            if f.get("url"):
                line += f" ({f['url']})"
            lines.append(line)
    return "\n".join(lines)


def news_since(research: str, since_date: str | None) -> list[dict]:
    """News facts in RESEARCH dated strictly after since_date (YYYY-MM-DD).

    Only these can be "new" in What changed: news dated on or before the
    previous dossier existed back then, even if the previous research missed
    it. News without a valid date is never new. Returns [] without since_date.
    """
    try:
        since = date.fromisoformat(since_date or "")
    except ValueError:
        return []
    result = []
    for fact in parse_research(research or ""):
        if fact.kind != "fact" or not fact.section.lower().startswith("recent news"):
            continue
        try:
            when = date.fromisoformat((fact.date or "").strip())
        except ValueError:
            continue
        if when > since:
            result.append({"claim": fact.claim, "date": when.isoformat(), "url": fact.url})
    return result


def format_news_since(news: list[dict], since_date: str | None) -> str:
    """Text for the writer's NEW NEWS block. Empty when there is no previous
    dossier (What changed is then [Pending] anyway)."""
    if not since_date:
        return ""
    if not news:
        return f"None: no news item in RESEARCH is dated after {since_date}."
    return "\n".join(f"- {n['claim']} (date: {n['date']})" for n in news)
