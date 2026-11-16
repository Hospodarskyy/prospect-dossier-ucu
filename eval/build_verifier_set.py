"""Build the labelled set of the SourceVerifier evaluation (free, no model).

Takes pages that the eval runs fetched (the page cache of the pipeline),
copies them to eval/data/verifier/pages/ (so the eval works without the
cache), and writes eval/data/verifier/cases.jsonl. The label of every case is
known by construction:

  exact              quote = a sentence of the page             -> supported
  format_noise       same, other case/spaces/quote marks        -> supported
  word_swap          a third of the words replaced              -> not_found
  other_page         a sentence of another page (not on this one) -> not_found
  overstated_strong  claim adds a lot the quote does not say    -> supported + weak
  overstated_subtle  claim adds a superlative to the sentence   -> supported + weak
  number_changed     claim changes a number of the sentence     -> supported + weak
  date_on_page       fact date that is on the page              -> date check "exact"
  date_not_on_page   fact date that is not on the page          -> date check "missing"

Hand-labelled real facts are in eval/data/verifier_manual.jsonl.

Run from the repo root after eval.collect_runs:  python -m eval.build_verifier_set
"""
import hashlib
import json
import random
import re
import sys
import urllib.parse

from dossier_agent.verification import _cache_file, check_date_on_page, match_ratio

from eval.components.common import DATA_DIR, ROOT, load_runs

CACHE_DIR = ROOT / "data" / "cache" / "pages"
OUT_DIR = DATA_DIR / "verifier"
PAGES_DIR = OUT_DIR / "pages"
MAX_PAGES = 20
MAX_PAGE_CHARS = 40_000
SEED = 7
SWAP_WORDS = ["banana", "glacier", "violin", "orbit", "pepper", "harbor", "lantern", "meadow"]
STRONG_ADDITION = (" It is the undisputed market leader across Europe, doubled annual revenue "
                   "last year and employs over 900 engineers.")
SUBTLE_ADDITION = "largest and fastest-growing "
DATE_NOT_ON_PAGE = "2019-02-13"
MONTHS = ("January February March April May June July August September October November "
          "December").split()
_DATE_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_DATE_LONG = re.compile(r"\b(" + "|".join(MONTHS) + r") (\d{1,2}), (20\d\d)\b")
_NUMBER = re.compile(r"\b\d[\d,]*\b")


def page_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def pick_pages() -> list[dict]:
    """Pages behind supported facts of the eval runs, at most 4 per domain."""
    pages, per_domain, seen = [], {}, set()
    for run in load_runs():
        for iteration in run.iterations:
            for fact in iteration.get("facts") or []:
                url = fact.get("url")
                if fact.get("status") != "supported" or not url or url in seen:
                    continue
                seen.add(url)
                cached = _cache_file(CACHE_DIR, url)
                if not cached.exists():
                    continue
                page = json.loads(cached.read_text(encoding="utf-8"))
                final = page.get("final_url") or url
                domain = urllib.parse.urlparse(final).netloc
                if per_domain.get(domain, 0) >= 4 or len(page.get("text", "")) < 1500:
                    continue
                per_domain[domain] = per_domain.get(domain, 0) + 1
                pages.append({"id": page_id(final), "url": final,
                              "text": page["text"][:MAX_PAGE_CHARS]})
    return pages[:MAX_PAGES]


def sentences(text: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        words = s.split()
        alpha = sum(w.strip(".,;:!?()\"'").isalpha() for w in words)
        if 12 <= len(words) <= 35 and s[:1].isupper() and alpha >= 0.75 * len(words) \
                and "cookie" not in s.lower() and "©" not in s:
            out.append(s.strip())
    return out


def find_date(text: str) -> str | None:
    match = _DATE_ISO.search(text)
    if match:
        return match.group(0)
    match = _DATE_LONG.search(text)
    if match:
        month = MONTHS.index(match.group(1)) + 1
        return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"
    return None


def swap_words(sentence: str, rng: random.Random) -> str:
    words = sentence.split()
    for i in range(1, len(words), 3):
        words[i] = rng.choice(SWAP_WORDS)
    return " ".join(words)


def change_number(sentence: str) -> str | None:
    match = _NUMBER.search(sentence)
    if not match:
        return None
    value = int(match.group(0).replace(",", ""))
    return sentence[: match.start()] + str(value * 3 + 7) + sentence[match.end():]


def subtle(sentence: str) -> str:
    """The sentence with a superlative the page does not support."""
    match = re.search(r"\b(a|an|the) ", sentence)
    if match:
        return sentence[: match.start()] + "the " + SUBTLE_ADDITION + sentence[match.end():]
    return sentence.rstrip(".!? ") + ", the largest and fastest-growing in its market."


def build_cases(pages: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    picked = {}
    for page in pages:
        candidates = sentences(page["text"])
        if candidates:
            picked[page["id"]] = rng.choice(candidates)
    ids = list(picked)
    cases = []

    def add(variant, page, claim, quote, status, weak=None, date=None, date_check=None):
        cases.append({"id": f"{page}-{variant}", "variant": variant, "page": page,
                      "claim": claim, "quote": quote, "date": date,
                      "expect_status": status, "expect_weak": weak,
                      "expect_date": date_check, "source": "synthetic"})

    for n, pid in enumerate(ids):
        s = picked[pid]
        text = next(p["text"] for p in pages if p["id"] == pid)
        add("exact", pid, s, s, "supported", False)
        noisy = "  ".join(s.lower().split()).replace("'", "’") + " ..."
        add("format_noise", pid, s, noisy, "supported", False)
        add("word_swap", pid, s, swap_words(s, rng), "not_found")
        other = picked[ids[(n + 1) % len(ids)]]
        # pages of one site share boilerplate: only a sentence that is really not here
        if other != s and match_ratio(other, text) < 0.5:
            add("other_page", pid, other, other, "not_found")
        add("overstated_strong", pid, " ".join(s.split()[:6]) + "." + STRONG_ADDITION, s,
            "supported", True)
        add("overstated_subtle", pid, subtle(s), s, "supported", True)
        changed = change_number(s)
        if changed and changed not in text:
            add("number_changed", pid, changed, s, "supported", True)
        date = find_date(text)
        if date and check_date_on_page(date, text) == "exact":
            add("date_on_page", pid, s, s, "supported", False, date, "exact")
        if check_date_on_page(DATE_NOT_ON_PAGE, text) == "missing":
            add("date_not_on_page", pid, s, s, "supported", False, DATE_NOT_ON_PAGE, "missing")
    return cases


def main() -> None:
    pages = pick_pages()
    if not pages:
        sys.exit("no cached pages of eval runs: run python -m eval.collect_runs first")
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    manual = DATA_DIR / "verifier_manual.jsonl"
    keep = {json.loads(l)["page"] for l in manual.read_text(encoding="utf-8").splitlines()
            if l.strip()} if manual.exists() else set()
    for old in PAGES_DIR.glob("*.json"):
        if old.stem not in keep:          # pages of the hand-labelled cases stay
            old.unlink()
    for page in pages:
        (PAGES_DIR / f"{page['id']}.json").write_text(
            json.dumps(page, ensure_ascii=False), encoding="utf-8")
    cases = build_cases(pages)
    with open(OUT_DIR / "cases.jsonl", "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"{len(pages)} pages, {len(cases)} cases -> {OUT_DIR}")


if __name__ == "__main__":
    main()
