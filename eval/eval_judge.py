"""Evaluate the judge agent on mutated research fixtures (no researcher, no search).

A clean baseline research text is corrupted in controlled ways ("mutations").
The expected status is known by construction, so we can score the judge.

Run from the repo root:  python -m eval.eval_judge
"""
import asyncio
import json
import os
import pathlib
import re
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

# Load .env BEFORE importing the agent: MODEL is read at import time.
load_dotenv("dossier_agent/.env")

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from dossier_agent.agent import judge
from dossier_agent.verification import format_verification, verify_research

BASE_FIXTURE = pathlib.Path("data/fixtures/research_plausible.md")
RESULTS_DIR = pathlib.Path("eval/results")
CACHE_DIR = pathlib.Path("data/cache/pages")  # same cache as the pipeline
TODAY = date(2026, 10, 29)  # fixed so the "older than 90 days" check is reproducible
# What the user typed in the real pipeline (same text as state["request"]).
REQUEST = "Company: Plausible Analytics\nDomain: plausible.io"
APP_NAME = "judge_eval"
USER_ID = "eval"

URL_RE = re.compile(r"https?://[^\s)\]]+")
HEADING_RE = re.compile(r"^#{1,3} ", re.MULTILINE)
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
PENDING_FACT = "- [Pending] no data found"

# Unrelated pages: judge should not accept them as support for company facts.
UNRELATED_URLS = [
    "https://en.wikipedia.org/wiki/Banana",
    "https://en.wikipedia.org/wiki/Roman_Empire",
    "https://en.wikipedia.org/wiki/Photosynthesis",
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def split_sections(text: str) -> tuple[str, list[str]]:
    """Return (preamble, sections); each section starts with its heading line."""
    starts = [m.start() for m in HEADING_RE.finditer(text)]
    if not starts:
        return text, []
    preamble = text[: starts[0]]
    bounds = starts + [len(text)]
    return preamble, [text[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


def join_sections(preamble: str, sections: list[str]) -> str:
    return preamble + "".join(sections)


def is_fact(line: str) -> bool:
    return line.lstrip().startswith("- ")


# --------------------------------------------------------------------------
# Mutations: text -> text
# --------------------------------------------------------------------------
def baseline(text: str) -> str:
    return text


def strip_all_urls(text: str) -> str:
    """Remove every URL (and the surrounding '(source: ...)' wrapper)."""
    text = re.sub(r"\s*\((?:source:\s*)?https?://[^)\s]+\)", "", text)
    return URL_RE.sub("", text)


def strip_one_url(text: str) -> str:
    """Remove the URL of the first sourced fact only."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if is_fact(line) and URL_RE.search(line):
            line = re.sub(r"\s*\((?:source:\s*)?https?://[^)\s]+\)", "", line)
            lines[i] = URL_RE.sub("", line)
            break
    return "\n".join(lines)


def swap_all_urls_unrelated(text: str) -> str:
    """Replace every URL with an unrelated Wikipedia page (round robin)."""
    counter = iter(range(10_000))
    return URL_RE.sub(lambda m: UNRELATED_URLS[next(counter) % len(UNRELATED_URLS)], text)


def swap_one_url_unrelated(text: str) -> str:
    """Replace only the first URL: a harder, more realistic case."""
    return URL_RE.sub(UNRELATED_URLS[0], text, count=1)


def make_news_stale(text: str) -> str:
    """Shift every ISO date (YYYY-MM-DD) to ~400 days before TODAY."""
    old = TODAY - timedelta(days=400)
    return ISO_DATE_RE.sub(old.isoformat(), text)


def fake_news_dates(text: str) -> str:
    """Replace every ISO date with a recent one that is not on any source page."""
    fake = (TODAY - timedelta(days=20)).isoformat()
    return ISO_DATE_RE.sub(fake, text)


def empty_second_section(text: str) -> str:
    """Keep the heading of the 2nd section but remove its body."""
    pre, sections = split_sections(text)
    if len(sections) >= 2:
        heading = sections[1].splitlines()[0]
        sections[1] = heading + "\n\n"
    return join_sections(pre, sections)


def drop_second_section(text: str) -> str:
    pre, sections = split_sections(text)
    if len(sections) >= 2:
        del sections[1]
    return join_sections(pre, sections)


def all_pending(text: str) -> str:
    """Every fact becomes '[Pending] no data found' (honest, so it should pass)."""
    lines = [PENDING_FACT if is_fact(line) else line for line in text.splitlines()]
    return "\n".join(lines)


def reverse_bullets(text: str) -> str:
    """Reverse the order of bullets inside each section (harmless change)."""
    pre, sections = split_sections(text)
    out = []
    for section in sections:
        lines = section.splitlines()
        heading, body = lines[0], lines[1:]
        facts = [l for l in body if is_fact(l)]
        facts.reverse()
        it = iter(facts)
        body = [next(it) if is_fact(l) else l for l in body]
        out.append("\n".join([heading] + body) + "\n")
    return join_sections(pre, out)


def _overstate(text: str, additions: list[str]) -> str:
    """Append a claim the quote does not support to the first sourced facts
    (the quote and URL stay the same, so the quote is still found)."""
    lines, it = text.splitlines(), iter(additions)
    for i, line in enumerate(lines):
        if is_fact(line) and "(source:" in line:
            addition = next(it, None)
            if addition is None:
                break
            head, tail = line.split(" (source:", 1)
            lines[i] = f"{head.rstrip('. ')}{addition} (source:{tail}"
    return "\n".join(lines)


def overstate_claims(text: str) -> str:
    """Two facts claim much more than their quotes say."""
    return _overstate(text, [", and it is the clear market leader in Europe with over "
                             "1 million paying customers",
                             ", and its revenue grew tenfold in 2025"])


def overstate_one_subtle(text: str) -> str:
    """One fact adds a superlative its quote does not support (harder)."""
    return _overstate(text, [", making it the most popular analytics tool in Europe"])


# name -> (function, expected status, group)
MUTATIONS = {
    "baseline":              (baseline,               "pass", "benign"),
    "reverse_bullets":       (reverse_bullets,        "pass", "benign"),
    "all_pending":           (all_pending,            "pass", "benign"),
    "strip_all_urls":        (strip_all_urls,         "fail", "structural"),
    "strip_one_url":         (strip_one_url,          "fail", "structural"),
    "stale_news":            (make_news_stale,        "fail", "structural"),
    "empty_section":         (empty_second_section,   "fail", "structural"),
    "drop_section":          (drop_second_section,    "fail", "structural"),
    "fake_date":             (fake_news_dates,        "fail", "semantic"),
    "swap_all_urls":         (swap_all_urls_unrelated, "fail", "semantic"),
    "swap_one_url":          (swap_one_url_unrelated, "fail", "semantic"),
    "overstate_claims":      (overstate_claims,       "fail", "semantic"),
    "overstate_one_subtle":  (overstate_one_subtle,   "fail", "semantic"),
}


# --------------------------------------------------------------------------
# Running the judge
# --------------------------------------------------------------------------
async def run_judge(research: str) -> tuple[dict, str, dict]:
    """Mimic the pipeline step by step: SourceVerifier, then the judge.

    Returns (judge feedback, verification report, token usage of the judge).
    """
    # Same call as SourceVerifier in agent.py (real downloads, cached on disk).
    try:
        report = format_verification(await verify_research(research, cache_dir=CACHE_DIR))
    except Exception as exc:
        report = f"SOURCE VERIFICATION: ERROR ({type(exc).__name__}: {exc})"

    service = InMemorySessionService()
    session = await service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={
            "research": research,
            "today": TODAY.isoformat(),
            "verification": report,
            "request": REQUEST,
        },
    )
    runner = Runner(agent=judge, app_name=APP_NAME, session_service=service)
    message = types.Content(role="user", parts=[types.Part(text=REQUEST)])

    usage = {"input": 0, "output": 0, "thinking": 0}
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session.id, new_message=message
    ):
        um = event.usage_metadata
        if um:
            usage["input"] += um.prompt_token_count or 0
            usage["output"] += um.candidates_token_count or 0
            usage["thinking"] += um.thoughts_token_count or 0

    final = await service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    feedback = final.state.get("judge_feedback")
    # output_schema may be stored as a dict or as a JSON string
    if isinstance(feedback, str):
        feedback = json.loads(feedback)
    return (feedback or {}), report, usage


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def compute_metrics(rows: list[dict]) -> dict:
    """'fail' is the positive class: the judge is there to catch bad research."""
    tp = sum(r["expected"] == "fail" and r["got"] == "fail" for r in rows)
    fp = sum(r["expected"] == "pass" and r["got"] == "fail" for r in rows)
    fn = sum(r["expected"] == "fail" and r["got"] != "fail" for r in rows)
    tn = sum(r["expected"] == "pass" and r["got"] == "pass" for r in rows)
    total = len(rows)
    return {
        "total": total,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": (tp + tn) / total if total else None,
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "recall": tp / (tp + fn) if (tp + fn) else None,
    }


def metrics_by_group(rows: list[dict]) -> dict:
    groups = sorted({r["group"] for r in rows})
    return {g: compute_metrics([r for r in rows if r["group"] == g]) for g in groups}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
async def main() -> None:
    base_text = BASE_FIXTURE.read_text(encoding="utf-8")
    rows = []

    for name, (mutate, expected, group) in MUTATIONS.items():
        mutated = mutate(base_text)
        feedback, report, usage = await run_judge(mutated)
        got = feedback.get("status", "error")
        rows.append({
            "mutation": name,
            "group": group,
            "expected": expected,
            "got": got,
            "ok": got == expected,
            "summary": feedback.get("summary", ""),
            "feedback": feedback,
            "verification": report,
            "usage": usage,
            "mutated_text": mutated,  # saved so each case can be inspected later
        })
        print(f"{name:<18} [{group:<10}] expected={expected:<5} got={got:<5} "
              f"{'OK' if rows[-1]['ok'] else 'MISMATCH'}")
        print(f"    {report.splitlines()[0]}")

    total = {k: sum(r["usage"][k] for r in rows) for k in ("input", "output", "thinking")}
    # what the judge really uses (unset env = the agent's default, "low")
    config = judge.generate_content_config.thinking_config if judge.generate_content_config else None
    thinking_level = config.thinking_level.value.lower() if config and config.thinking_level else "default"
    model = os.getenv("MODEL", "?")
    print(f"\nJudge tokens over {len(rows)} cases (model={model}, thinking_level={thinking_level}): {total}")

    overall = compute_metrics(rows)
    per_group = metrics_by_group(rows)
    print("\nOverall:", json.dumps(overall, indent=2))
    print("By group:", json.dumps(per_group, indent=2))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"judge_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(
        json.dumps(
            {"today": TODAY.isoformat(), "model": model, "thinking_level": thinking_level,
             "usage": total, "overall": overall,
             "by_group": per_group, "rows": rows},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())