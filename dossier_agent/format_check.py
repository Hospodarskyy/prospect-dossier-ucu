import re

# fact sections in dossier order; then "<seller> angle" and "What changed"
FACT_SECTION_ORDER = ["Snapshot", "Recent news", "Tech signals", "Key people", "Likely pains"]
FACT_SECTIONS = set(FACT_SECTION_ORDER)
CHANGES_SECTION = "What changed"
SOURCES_SECTION = "Sources"

URL_RE = re.compile(r"https?://\S+")
PENDING_PREFIX = "- [Pending]"
HYPOTHESIS_PREFIX = "- Hypothesis:"
NOTE_PREFIX = "Note:"
MAX_WORDS = 900          # about two pages
MAX_HYPOTHESES = 5       # Likely pains: 3-5 hypotheses (minimum is soft: pending_human)


def required_sections(angle_section: str) -> list[str]:
    """All '##' sections of a dossier, in order. angle_section is
    '<seller> angle' (seller_cases.angle_section)."""
    return FACT_SECTION_ORDER + [angle_section, CHANGES_SECTION]


def _fail(message: str) -> dict:
    return {"success": False, "message": message}


def _split_sections(md: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (lines before the first '## ', [(section_name, body), ...] in order)."""
    preamble: list[str] = []
    sections: list[tuple[str, str]] = []
    name: str | None = None
    body_lines: list[str] = []

    for line in md.splitlines():
        if line.startswith("## "):
            if name is not None:
                sections.append((name, "\n".join(body_lines).strip()))
            name = line[3:].strip()
            body_lines = []
        elif name is not None:
            body_lines.append(line)
        else:
            preamble.append(line)

    if name is not None:
        sections.append((name, "\n".join(body_lines).strip()))
    return preamble, sections


def _check_title(preamble: list[str]) -> str | None:
    """Exactly one '# Title' first; only an optional 'Note:' line may follow."""
    lines = [l.strip() for l in preamble if l.strip()]
    if not lines or not lines[0].startswith("# "):
        return "The dossier must start with a single '# <Company name>' title"
    extra = lines[1:]
    if any(not l.startswith(NOTE_PREFIX) for l in extra) or len(extra) > 1:
        return ("Only one optional 'Note: ...' line is allowed between the title "
                "and the first section")
    return None


def check_dossier_format(md: str, *, angle_section: str) -> dict:
    required = required_sections(angle_section)
    preamble, sections = _split_sections(md or "")

    # 1. title (and optional note)
    problem = _check_title(preamble)
    if problem:
        return _fail(problem)

    names = [name for name, _ in sections]

    # 2. every required section is present
    missing = [s for s in required if s not in names]
    if missing:
        return _fail("Missing section(s): " + ", ".join(missing))

    # 3. required sections appear once each, in the required order
    present = [n for n in names if n in required]
    if present != required:
        return _fail(
            "Sections are duplicated or out of order. Expected order: "
            + ", ".join(required)
        )

    # 4. bodies are non-empty; facts are sourced, pending, or hypotheses
    for name, body in sections:
        if name not in required:
            continue
        if not body:
            return _fail(f"Section '{name}' is empty: write '- [Pending]' if there is no data")
        if name not in FACT_SECTIONS:
            continue
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            if line.startswith(PENDING_PREFIX):
                continue
            if URL_RE.search(line):
                if name == "Key people" and "," not in URL_RE.split(line)[0]:
                    return _fail(f"Section 'Key people': write '- <Name>, <job title> (<URL>)': {line}")
                continue
            if line.startswith(HYPOTHESIS_PREFIX):
                return _fail(f"Section '{name}': hypothesis without the URL of the fact "
                             f"it is based on: {line}")
            return _fail(f"Section '{name}': fact without a URL: {line}")

    # 5. at most MAX_HYPOTHESES hypotheses in Likely pains
    for name, body in sections:
        if name == "Likely pains":
            n = sum(l.strip().startswith(HYPOTHESIS_PREFIX) for l in body.splitlines())
            if n > MAX_HYPOTHESES:
                return _fail(f"Likely pains has {n} hypotheses: keep the {MAX_HYPOTHESES} "
                             "best supported ones.")

    # 6. length
    words = len((md or "").split())
    if words > MAX_WORDS:
        return _fail(f"The dossier is too long: {words} words (at most {MAX_WORDS}). "
                     "Shorten it: keep the most important facts, drop minor ones.")

    return {"success": True, "message": "Format is valid."}



def extract_urls(text: str) -> set[str]:
    """All URLs in a text, without trailing punctuation like ')' or '.'."""
    return {u.rstrip(").,;]\"'") for u in URL_RE.findall(text or "")}


def check_dossier_urls(md: str, research: str, case_study_urls: set[str], *,
                       angle_section: str) -> dict:
    """Every URL in the dossier must come from somewhere we trust.

    - fact sections: only URLs that appear in the research text;
    - the angle section: only URLs of case studies returned by
      load_seller_cases in this run (none loaded: no URLs at all).

    Returns {"success": bool, "message": str}.
    """
    allowed_facts = extract_urls(research)
    _, sections = _split_sections(md or "")
    problems = []
    for name, body in sections:
        if name in FACT_SECTIONS:
            unknown = sorted(extract_urls(body) - allowed_facts)
            if unknown:
                problems.append(f"Section '{name}' has URLs that are not in RESEARCH "
                                f"(copy them exactly): {', '.join(unknown)}")
        elif name == angle_section:
            unknown = sorted(extract_urls(body) - set(case_study_urls))
            if unknown:
                problems.append(f"{angle_section} cites URLs of case studies that "
                                "load_seller_cases did not return: " + ", ".join(unknown))
    if problems:
        return _fail("; ".join(problems))
    return {"success": True, "message": "All URLs come from RESEARCH or load_seller_cases."}


def check_dossier(md: str, research: str, case_study_urls: set[str], *,
                  angle_section: str) -> dict:
    """Format check, then URL provenance check. Returns {"success", "message"}."""
    result = check_dossier_format(md, angle_section=angle_section)
    if not result["success"]:
        return result
    return check_dossier_urls(md, research, case_study_urls, angle_section=angle_section)
