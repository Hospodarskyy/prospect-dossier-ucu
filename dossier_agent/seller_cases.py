import re

from .storage import Storage, get_storage

CASES_KEY = "config/seller_cases.md"
MAX_CANDIDATES = 5

# first line of the file: "# Seller: <name>"; the name becomes the dossier
# section "<name> angle", so it is limited to a safe, short set of characters
_SELLER_RE = re.compile(r"^#\s+Seller:\s*(.+?)\s*$")
_SELLER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&'-]{0,59}$")
_HEADING_RE = re.compile(r"^##\s+([^:]+?)\s*:\s*(.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s*([A-Za-z]+)\s*:\s*(.*?)\s*$")
_FIELDS = {"industry", "technologies", "problem", "result", "url"}


class ConfigError(RuntimeError):
    """A required config file is missing or invalid: the run cannot start."""


def angle_section(seller: str) -> str:
    """Name of the dossier section written for this seller."""
    return f"{seller} angle"


def parse_seller_name(md: str) -> str:
    """The seller name from the '# Seller: <name>' line (the first non-empty
    line of the file). Raises ConfigError if it is missing or invalid."""
    first = next((l.strip() for l in (md or "").splitlines() if l.strip()), "")
    match = _SELLER_RE.match(first)
    if not match:
        raise ConfigError(f"{CASES_KEY}: the first line must be '# Seller: <name>'")
    name = match.group(1)
    if not _SELLER_NAME_RE.match(name):
        raise ConfigError(f"{CASES_KEY}: invalid seller name {name!r} (letters, digits, "
                          "spaces and . & ' - only, at most 60 characters)")
    return name


def parse_seller_cases(md: str) -> list[dict]:
    """Parse the case file. Raises ConfigError on a case without a URL or
    with a duplicate id. Text outside '## ' sections is ignored."""
    cases, current = [], None
    for raw in (md or "").splitlines():
        line = raw.strip()
        heading = _HEADING_RE.match(line)
        if heading:
            current = {"id": heading.group(1).strip(), "title": heading.group(2).strip(),
                       "industry": "", "technologies": [], "problem": "", "result": "", "url": ""}
            cases.append(current)
            continue
        field = _FIELD_RE.match(line)
        if current is None or not field:
            continue
        key, value = field.group(1).lower(), field.group(2)
        if key not in _FIELDS:
            continue
        if key == "technologies":
            current[key] = [t.strip() for t in value.split(",") if t.strip()]
        else:
            current[key] = value

    ids = set()
    for case in cases:
        if not case["url"].startswith(("http://", "https://")):
            raise ConfigError(f"{CASES_KEY}: case {case['id']!r} has no valid URL")
        if case["id"] in ids:
            raise ConfigError(f"{CASES_KEY}: duplicate case id {case['id']!r}")
        ids.add(case["id"])
    return cases


def load_cases_file(storage: Storage | None = None) -> tuple[str, list[dict]]:
    """Read and parse config/seller_cases.md: (seller name, cases). Raises
    ConfigError if the file is missing, cannot be parsed or has no cases."""
    text = (storage or get_storage()).read_text(CASES_KEY)
    if text is None:
        raise ConfigError(f"{CASES_KEY} not found in storage (copy demo-data/{CASES_KEY} "
                          f"to data/storage/{CASES_KEY})")
    seller = parse_seller_name(text)
    cases = parse_seller_cases(text)
    if not cases:
        raise ConfigError(f"{CASES_KEY} has no case studies ('## <id>: <title>' sections)")
    return seller, cases


# Names the writer may use for the same industry. A company matches a case
# when both mention a name of the same group ("Healthcare" ~ "HealthTech").
INDUSTRY_GROUPS = {
    "saas": ("saas", "software", "software as a service", "b2b software", "analytics",
             "developer tools", "devtools"),
    "e-commerce": ("e-commerce", "ecommerce", "online retail", "retail", "online store",
                   "marketplace"),
    "healthtech": ("healthtech", "health tech", "healthcare", "health care", "digital health",
                   "medtech", "medical"),
}


def _words(text: str) -> set[str]:
    """Lower-case words; dots stay inside a word ("node.js") but not at its ends
    ("payments." -> "payments")."""
    words = (w.strip(".") for w in re.findall(r"[a-z0-9+#.]+", (text or "").lower()))
    return {w for w in words if w}


def _phrase(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9+#]+", (text or "").lower())) + " "


def industry_groups(industry: str) -> set[str]:
    """INDUSTRY_GROUPS keys whose names occur in INDUSTRY ("Healthcare SaaS"
    -> {"healthtech", "saas"}); an unknown industry is its own group."""
    text = _phrase(industry)
    groups = {key for key, names in INDUSTRY_GROUPS.items()
              if any(_phrase(name) in text for name in names)}
    if not groups and text.strip():
        groups = {text.strip()}
    return groups


def select_candidates(cases: list[dict], industry: str, tech: list[str],
                      limit: int = MAX_CANDIDATES) -> list[dict]:
    company_groups = industry_groups(industry)
    terms = [t.strip().lower() for t in (tech or []) if isinstance(t, str) and t.strip()]

    def score(case: dict) -> int:
        s = 0
        if company_groups & industry_groups(case["industry"]):
            s += 2
        techs = {t.lower() for t in case["technologies"]}
        words = _words(case["problem"] + " " + case["result"])
        for term in terms:
            term_words = _words(term)
            if term in techs or (term_words and term_words <= words):
                s += 1
        return s

    ranked = sorted(enumerate(cases), key=lambda ic: (-score(ic[1]), ic[0]))
    return [case for _, case in ranked[:limit]]
