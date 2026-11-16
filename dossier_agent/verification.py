"""Source verification for the dossier pipeline: parse -> fetch -> compare.

Everything here is plain Python (no ADK imports) so it can be tested offline.
The ADK wrapper (SourceVerifier) lives in agent.py and only calls
verify_research() + format_verification().

Expected research format (see RESEARCHER_INSTRUCTION):
    ## Section
    - claim (date: YYYY-MM-DD) (source: URL) (quote: "exact words")
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import re
import unicodedata
from datetime import date as _date
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx
from bs4 import BeautifulSoup

# Wikimedia and some other sites reject default library user agents.
# Put your own contact here.
USER_AGENT = "ProspectDossierBot/0.1 (student project; contact: you@example.com)"
SECTION_NAMES = {
    "snapshot", "recent news", "tech signals", "key people", "business pains",
}
MATCH_THRESHOLD = 0.8        # share of quote words found as one continuous run
WEAK_COVERAGE = 0.6          # min share of the claim's key words that the quote must contain
EXCERPT_CONTEXT = 200        # chars of page text kept around the matched fragment
MAX_EXCERPT_CHARS = 450      # hard cap for one excerpt
MAX_EXCERPTS = 8             # excerpts per report (the rest are listed without one)
MIN_FRAGMENT_TOKENS = 3      # shorter overlaps are noise, not a "closest fragment"
DATE_EXACT = "exact"        # full date found on the page
DATE_MONTH = "month"        # only month + year found (page is less precise than the fact)
DATE_MISSING = "missing"     # neither found: the date looks invented
HEAD_CHARS = 300             # how much research text is shown on a parse error
MAX_PAGE_CHARS = 2_000_000
REQUEST_TIMEOUT = 15.0

# Statuses assigned to every fact.
SUPPORTED = "supported"
NOT_FOUND = "not_found"
MISSING_SOURCE = "missing_source"
MISSING_QUOTE = "missing_quote"
UNREACHABLE = "unreachable"   # blocked, timeout, network error: not the source's fault
DEAD_LINK = "dead_link"       # HTTP 404/410: the cited page does not exist
DEAD_LINK_CODES = (404, 410)


# --------------------------------------------------------------------------
# 1. Parser
# --------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(?P<name>.+?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+(?P<body>.+?)\s*$")
_DATE_RE = re.compile(r"\(date:\s*(\d{4}-\d{2}-\d{2})\s*\)")


@dataclass
class Fact:
    kind: str                      # "fact" | "pending" | "hypothesis"
    section: str
    claim: str
    url: Optional[str] = None
    quote: Optional[str] = None
    date: Optional[str] = None
    raw: str = ""


def _section_name(line: str) -> Optional[str]:
    """Return the section name if the line is a section heading, else None."""
    heading = _HEADING_RE.match(line)
    name = heading.group("name") if heading else line
    name = re.sub(r"^\d+[.)]\s*", "", name.strip().strip("*_ :").strip())
    if heading or name.lower() in SECTION_NAMES:
        return name or None
    return None


def _extract_url(body: str) -> Optional[str]:
    match = re.search(r"\(source:\s*(\S+)", body)
    if not match:
        return None
    url = match.group(1)
    # Drop the ")" that closes "(source: ...)" but keep ")" inside the URL,
    # e.g. https://en.wikipedia.org/wiki/Hello_(company)
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url if url.lower().startswith("http") else None


def _extract_quote(body: str) -> Optional[str]:
    start = body.find("(quote:")
    if start < 0:
        return None
    rest = body[start + len("(quote:"):].strip()
    if rest.endswith(")"):
        rest = rest[:-1].rstrip()
    if len(rest) >= 2 and rest[0] in "\"“" and rest[-1] in "\"”":
        rest = rest[1:-1]
    return rest.strip() or None


def _extract_claim(body: str) -> str:
    markers = [body.find(m) for m in ("(date:", "(source:", "(quote:")]
    cut = min([i for i in markers if i >= 0], default=len(body))
    return body[:cut].strip()


def parse_research(text: str) -> list[Fact]:
    """Turn research text into Fact records (one per bullet line).

    Bullets that are '[Pending]' or 'Hypothesis:' get their own kind.
    Lines that are neither bullets nor headings (e.g. 'Searches performed')
    are ignored.
    """
    facts: list[Fact] = []
    section = ""
    for line in (text or "").splitlines():
        bullet = _BULLET_RE.match(line)
        if not bullet:
            name = _section_name(line)
            if name:
                section = name
            continue
        body = bullet.group("body")
        plain = body.lstrip("*_ ").lower()
        if plain.startswith("[pending]"):
            facts.append(Fact("pending", section, body, raw=line))
        elif plain.startswith("hypothesis:"):
            facts.append(Fact("hypothesis", section, body, raw=line))
        else:
            date = _DATE_RE.search(body)
            facts.append(Fact(
                kind="fact",
                section=section,
                claim=_extract_claim(body),
                url=_extract_url(body),
                quote=_extract_quote(body),
                date=date.group(1) if date else None,
                raw=line,
            ))
    return facts


# --------------------------------------------------------------------------
# 2. Comparer
# --------------------------------------------------------------------------
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has",
    "have", "had", "its", "their", "his", "her", "our", "your", "not", "but", "into",
    "than", "then", "also", "which", "who", "whom", "been", "being", "will", "can",
    "all", "any", "more", "most", "such", "over", "per", "via", "inc", "ltd",
}


def _clean(text: str) -> str:
    """NFKC-normalise and blank out footnote markers like '[ 1 ]' (length is kept)."""
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\[\s*\d+\s*\]", lambda m: " " * len(m.group()), text)


def _spans(clean: str) -> list[tuple[str, int, int]]:
    """(lowercase token, start, end) for every word/number in already cleaned text."""
    return [(m.group().lower(), m.start(), m.end()) for m in re.finditer(r"\w+", clean)]


def tokenize(text: str) -> list[str]:
    """Lowercase words and numbers; footnote markers like '[ 1 ]' are dropped."""
    return [t for t, _, _ in _spans(_clean(text))]


def best_fragment(quote: str, page_text: str) -> tuple[int, Optional[tuple[int, int]]]:
    """Longest run of quote words found on the page.

    Returns (run length in words, (start, end) char offsets in _clean(page_text)),
    or (0, None) when nothing overlaps.
    """
    q = tokenize(quote)
    spans = _spans(_clean(page_text))
    if not q or not spans:
        return 0, None
    matcher = difflib.SequenceMatcher(None, [t for t, _, _ in spans], q, autojunk=False)
    m = matcher.find_longest_match(0, len(spans), 0, len(q))
    if m.size == 0:
        return 0, None
    return m.size, (spans[m.a][1], spans[m.a + m.size - 1][2])


def match_ratio(quote: str, page_text: str) -> float:
    """Share of the quote's words that appear as one continuous run on the page."""
    q = tokenize(quote)
    if not q:
        return 0.0
    size, _ = best_fragment(quote, page_text)
    return size / len(q)


def make_excerpt(page_text: str, span: tuple[int, int]) -> str:
    """Page text around a matched fragment, whitespace-collapsed and length-capped."""
    clean = _clean(page_text)
    lo = max(0, span[0] - EXCERPT_CONTEXT)
    hi = min(len(clean), span[1] + EXCERPT_CONTEXT)
    text = re.sub(r"\s+", " ", clean[lo:hi]).strip()
    cut = len(text) > MAX_EXCERPT_CHARS
    if cut:
        text = text[:MAX_EXCERPT_CHARS].rstrip()
    return ("..." if lo > 0 else "") + text + ("..." if cut or hi < len(clean) else "")


def content_tokens(text: str) -> list[str]:
    """Words that carry meaning: no stop words, no 1-2 letter words (numbers stay)."""
    return [t for t in tokenize(text)
            if t not in STOPWORDS and (len(t) > 2 or t.isdigit())]


def claim_coverage(claim: str, quote: str) -> float:
    """Share of the claim's key words that also occur in the quote (1.0 if no key words)."""
    key = set(content_tokens(claim))
    if not key:
        return 1.0
    return len(key & set(tokenize(quote))) / len(key)


def _normalize_numbers(text: str) -> str:
    """'30,000' -> '30000' and '30k' -> '30000', so spellings of one number compare equal."""
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text or "")
    return re.sub(r"\b(\d+)k\b", lambda m: str(int(m.group(1)) * 1000), text, flags=re.I)


def missing_numbers(claim: str, page_text: str) -> list[str]:
    """Numbers from the claim that never appear on the page (informational)."""
    page_tokens = set(tokenize(_normalize_numbers(page_text)))
    return [t for t in tokenize(_normalize_numbers(claim)) if t.isdigit() and t not in page_tokens]


_MONTHS = [
    ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
    ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
    ("september", "sept", "sep"), ("october", "oct"), ("november", "nov"),
    ("december", "dec"),
]


def check_date_on_page(date_str: str, page_text: str) -> Optional[str]:
    """Where does 'YYYY-MM-DD' appear on the page?

    Returns DATE_EXACT (full date in a common format), DATE_MONTH (only month and
    year, e.g. 'September 2026'), DATE_MISSING (neither), or None if date_str is
    not a valid date.
    """
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        _date(y, m, d)
    except (ValueError, AttributeError):
        return None
    text = unicodedata.normalize("NFKC", page_text or "").lower()
    month = "(?:" + "|".join(_MONTHS[m - 1]) + r")\.?"
    exact = [
        rf"(?<!\d){y}[-/.]0?{m}[-/.]0?{d}(?!\d)",                 # 2026-10-26, 2026/10/26
        rf"\b{month}\s+0?{d}(?:st|nd|rd|th)?,?\s+{y}\b",         # October 26, 2026
        rf"\b0?{d}(?:st|nd|rd|th)?\s+(?:of\s+)?{month},?\s+{y}\b",  # 26 October 2026
        rf"(?<!\d)0?{d}\.0?{m}\.{y}(?!\d)",                       # 26.10.2026
    ]
    if any(re.search(pattern, text) for pattern in exact):
        return DATE_EXACT
    if re.search(rf"\b{month},?\s+{y}\b", text) or re.search(rf"(?<!\d){y}-0?{m}(?![\d-])", text):
        return DATE_MONTH
    return DATE_MISSING


@dataclass
class FetchResult:
    ok: bool
    final_url: Optional[str] = None
    text: str = ""
    error: Optional[str] = None
    status_code: Optional[int] = None
    head: str = ""            # first characters of what the server sent (for trace.json)


BOT_CHALLENGE_ERROR = "bot_challenge"
# Phrases of bot-protection / challenge pages (Cloudflare and similar). Checked
# only on short pages, so an article that mentions "captcha" is not affected.
_CHALLENGE_MARKERS = (
    "just a moment...", "attention required", "checking your browser",
    "enable javascript and cookies to continue", "verify you are human",
    "verifying you are human", "cf-chl", "cf_chl", "ddos protection by",
    "please complete the security check", "are you a robot", "captcha",
    "access denied", "request blocked",
)
_CHALLENGE_MAX_TEXT = 3_000
HEAD_CHARS_TRACE = 200


def looks_like_bot_challenge(raw: str, text: str) -> bool:
    """True if the server sent a bot-protection page instead of the content:
    a short page that contains a typical challenge phrase."""
    if len(text) > _CHALLENGE_MAX_TEXT:
        return False
    sample = (raw[:20_000] + " " + text).lower()
    return any(marker in sample for marker in _CHALLENGE_MARKERS)


def verify_fact(fact: Fact, page: Optional[FetchResult]) -> dict:
    """Assign a status (and a weak_support flag) to one fact. Pure function, no network.

    Extra fields for the judge, depending on the status:
      supported + weak_support: excerpt around the matched quote
      not_found:                closest fragment of the page (if any) and page length
    """
    result = {
        "section": fact.section,
        "claim": fact.claim,
        "url": fact.url,
        "final_url": page.final_url if page else None,
        "match_ratio": None,
        "coverage": None,
        "weak_support": False,
        "missing_numbers": [],
        "detail": "",
        "excerpt": None,
        "page_chars": None,
        "date": fact.date,
        "date_check": None,
        # for trace.json: what the fetch really got
        "http_status": page.status_code if page else None,
        "fetch_error": page.error if page else None,
        "page_head": (page.head or page.text[:HEAD_CHARS_TRACE]) if page else None,
        "blocked": bool(page and (page.error or "").startswith(BOT_CHALLENGE_ERROR)),
    }
    if not fact.url:
        result["status"] = MISSING_SOURCE
        result["detail"] = "no source URL"
    elif not fact.quote:
        result["status"] = MISSING_QUOTE
        result["detail"] = "no quote given"
    elif page is None or not page.ok:
        dead = page is not None and page.status_code in DEAD_LINK_CODES
        result["status"] = DEAD_LINK if dead else UNREACHABLE
        result["detail"] = (page.error if page else "not fetched") or ""
    else:
        size, span = best_fragment(fact.quote, page.text)
        q_len = len(tokenize(fact.quote))
        ratio = size / q_len if q_len else 0.0
        result["match_ratio"] = round(ratio, 3)
        result["missing_numbers"] = missing_numbers(fact.claim, page.text)
        result["page_chars"] = len(page.text)
        if fact.date:
            result["date_check"] = check_date_on_page(fact.date, page.text) or DATE_MISSING
        if ratio >= MATCH_THRESHOLD:
            result["status"] = SUPPORTED
            coverage = claim_coverage(fact.claim, fact.quote)
            result["coverage"] = round(coverage, 3)
            reasons = []
            if coverage < WEAK_COVERAGE:
                reasons.append(f"quote contains only {coverage:.0%} of the claim's key words")
            if result["missing_numbers"]:
                reasons.append("numbers not on the page: " + ", ".join(result["missing_numbers"]))
            if reasons:
                result["weak_support"] = True
                result["detail"] = "; ".join(reasons)
                result["excerpt"] = make_excerpt(page.text, span)
        else:
            result["status"] = NOT_FOUND
            result["detail"] = (f"quote found as one run in {ratio:.0%} of its words; "
                                f"page has {len(page.text)} chars")
            if size >= MIN_FRAGMENT_TOKENS:
                result["excerpt"] = make_excerpt(page.text, span)
            else:
                result["detail"] += "; no overlapping text"
    return result


# --------------------------------------------------------------------------
# 3. Fetcher
# --------------------------------------------------------------------------
_META_DATE_KEYS = {
    "article:published_time", "article:modified_time", "og:updated_time",
    "datepublished", "datemodified", "date", "pubdate", "publishdate",
}


def html_to_text(html: str) -> str:
    """Visible text plus publication dates hidden in meta tags, <time> and JSON-LD.

    Those dates are not visible text but are what a news date usually comes from,
    so they are appended at the end as '[page dates: ...]'.
    """
    soup = BeautifulSoup(html, "html.parser")
    dates: list[str] = []
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower()
        if key in _META_DATE_KEYS and meta.get("content"):
            dates.append(meta["content"])
    for tag in soup.find_all("time"):
        if tag.get("datetime"):
            dates.append(tag["datetime"])
    for script in soup.find_all("script", type="application/ld+json"):
        dates += re.findall(r'"date(?:Published|Modified)"\s*:\s*"([^"]+)"', script.string or "")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    if dates:
        text += " [page dates: " + " ".join(dict.fromkeys(dates)) + "]"
    return text


async def fetch_page_text(url: str, client: httpx.AsyncClient) -> FetchResult:
    """Download a page (following redirects) and return its plain text."""
    try:
        response = await client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        return FetchResult(False, error=f"{type(exc).__name__}: {exc}")
    final_url = str(response.url)
    code = response.status_code
    content_type = response.headers.get("content-type", "").lower()
    is_html = "html" in content_type or not content_type
    body = response.text[:MAX_PAGE_CHARS] if (is_html or "text" in content_type) else ""
    text = html_to_text(body) if is_html and body else body
    head = re.sub(r"\s+", " ", text or body)[:HEAD_CHARS_TRACE]
    # a challenge page instead of the content: "could not check", not "not supported"
    if body and looks_like_bot_challenge(body, text):
        return FetchResult(False, final_url, error=f"{BOT_CHALLENGE_ERROR} (HTTP {code})",
                           status_code=code, head=head)
    if code != 200:
        return FetchResult(False, final_url, error=f"HTTP {code}", status_code=code, head=head)
    if content_type and not is_html and "text" not in content_type:
        return FetchResult(False, final_url, error=f"unsupported content type: {content_type}",
                           status_code=code)
    return FetchResult(True, final_url, text, status_code=code, head=head)


def _cache_file(cache_dir: Path, url: str) -> Path:
    # "v2": entries cached before meta dates were extracted are ignored
    return cache_dir / (hashlib.sha256(("v2:" + url).encode("utf-8")).hexdigest() + ".json")


async def fetch_with_cache(
    url: str, client: httpx.AsyncClient, cache_dir: Optional[Path]
) -> FetchResult:
    """Like fetch_page_text, but successful pages are cached on disk."""
    if cache_dir:
        path = _cache_file(cache_dir, url)
        if path.exists():
            return FetchResult(**json.loads(path.read_text(encoding="utf-8")))
    result = await fetch_page_text(url, client)
    if cache_dir and result.ok:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_file(cache_dir, url).write_text(
            json.dumps(asdict(result), ensure_ascii=False), encoding="utf-8"
        )
    return result


# --------------------------------------------------------------------------
# 4. Orchestration
# --------------------------------------------------------------------------
async def verify_research(
    research: str,
    *,
    cache_dir: Optional[Path] = None,
    fetch: Optional[Callable[[str], Awaitable[FetchResult]]] = None,
    concurrency: int = 5,
) -> dict:
    """Verify every fact in the research text.

    `fetch` can be injected in tests; by default pages are downloaded.
    Returns {"status": "ok" | "empty" | "parse_error", "counts": {...}, "facts": [...]}.
    """
    if not (research or "").strip():
        return {"status": "empty", "counts": {}, "facts": []}

    items = parse_research(research)
    if not items:
        return {"status": "parse_error", "counts": {}, "facts": [],
                "head": research.strip()[:HEAD_CHARS]}

    facts = [f for f in items if f.kind == "fact"]
    urls = sorted({f.url for f in facts if f.url and f.quote})
    pages: dict[str, FetchResult] = {}

    if urls:
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        ) as client:

            async def get(url: str) -> tuple[str, FetchResult]:
                async with semaphore:
                    if fetch is not None:
                        return url, await fetch(url)
                    return url, await fetch_with_cache(url, client, cache_dir)

            for url, page in await asyncio.gather(*(get(u) for u in urls)):
                pages[url] = page

    verified = [verify_fact(f, pages.get(f.url or "")) for f in facts]
    counts = Counter(v["status"] for v in verified)
    counts["pending"] = sum(f.kind == "pending" for f in items)
    counts["hypothesis"] = sum(f.kind == "hypothesis" for f in items)
    blocked = sum(v["blocked"] for v in verified)
    if blocked:
        counts["blocked"] = blocked        # a flag on some "unreachable" facts, not a status
    weak = sum(v["weak_support"] for v in verified)
    if weak:
        counts["weak_support"] = weak      # a flag on some "supported" facts, not a status
    for check, name in ((DATE_MISSING, "date_unverified"), (DATE_MONTH, "date_imprecise")):
        n = sum(v["date_check"] == check for v in verified)
        if n:
            counts[name] = n
    return {"status": "ok", "counts": dict(counts), "facts": verified}


def resolved_urls(result: dict) -> dict[str, str]:
    """{url written in the research: real page URL after redirects}.

    Google Search grounding gives redirect links
    (vertexaisearch.cloud.google.com/grounding-api-redirect/...); the page
    fetch follows them, so final_url is the real address. Only pages that
    loaded (not unreachable / dead_link) are used; unchanged URLs are left out.
    """
    mapping = {}
    for fact in result.get("facts", []):
        url, final = fact.get("url"), fact.get("final_url")
        if not url or not final or final == url:
            continue
        if fact.get("status") in (UNREACHABLE, DEAD_LINK):
            continue
        mapping[url] = final
    return mapping


_SEVERITY = {MISSING_SOURCE: 0, MISSING_QUOTE: 1, DEAD_LINK: 2, NOT_FOUND: 3,
             UNREACHABLE: 4, "weak_support": 5}


def _label(fact: dict) -> str:
    return "weak_support" if fact["status"] == SUPPORTED and fact.get("weak_support") \
        else fact["status"]


def format_verification(result: dict) -> str:
    """Compact text for the judge (stored in state['verification']).

    Clean supported facts are only counted. Every other fact gets one line with the
    reason; not_found and weak_support facts also get a page excerpt (at most
    MAX_EXCERPTS per report, most severe first). A date that is not on the page
    gets its own [date_unverified] line; a date that is only partly there
    (month, not day) is counted as date_imprecise but not listed.
    """
    if result["status"] == "empty":
        return "SOURCE VERIFICATION: research is empty."
    if result["status"] == "parse_error":
        head = (result.get("head") or "").replace("\n", " / ")
        return ("SOURCE VERIFICATION: PARSE ERROR. The research does not follow "
                "the required bullet format, so no fact could be checked."
                + (f"\nStart of the research text: {head}" if head else ""))
    counts = ", ".join(f"{k}={v}" for k, v in sorted(result["counts"].items()))
    lines = [f"SOURCE VERIFICATION (automatic script): {counts}"]
    problems = [f for f in result["facts"]
                if _label(f) != SUPPORTED or f.get("date_check") == DATE_MISSING]
    by_severity = sorted(problems, key=lambda f: _SEVERITY.get(_label(f), 9))
    with_excerpt = {id(f) for f in [f for f in by_severity if f.get("excerpt")][:MAX_EXCERPTS]}
    for fact in problems:
        url = fact["url"] or "no URL"
        if _label(fact) != SUPPORTED:
            detail = f" - {fact['detail']}" if fact.get("detail") else ""
            lines.append(f"- [{_label(fact)}] {fact['claim']} ({url}){detail}")
            if id(fact) in with_excerpt:
                lines.append(f'    page text: "{fact["excerpt"]}"')
        if fact.get("date_check") == DATE_MISSING:
            lines.append(f"- [date_unverified] {fact['claim']} ({url}) - the date "
                         f"{fact.get('date')} does not appear on the page")
    return "\n".join(lines)