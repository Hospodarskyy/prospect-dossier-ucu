import json
import re

MAX_DOMAIN_LEN = 253
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://")
_PORT_RE = re.compile(r":\d{1,5}$")
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalize_domain(raw: str) -> str:
    """Return a canonical domain like "plausible.io" or raise ValueError.

    Accepts common spellings: upper case, scheme, "www.", path, query,
    fragment, port, trailing dot. Anything else outside [a-z0-9.-] is rejected.
    """
    if not isinstance(raw, str):
        raise ValueError("domain must be a string")
    domain = raw.strip().lower()
    domain = _SCHEME_RE.sub("", domain)
    domain = re.split(r"[/?#]", domain, maxsplit=1)[0]
    if "@" in domain:
        raise ValueError(f"domain must not contain user info: {raw!r}")
    domain = _PORT_RE.sub("", domain)
    domain = domain.rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        raise ValueError(f"domain is empty: {raw!r}")
    if not domain.isascii():
        try:
            domain = domain.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"invalid internationalized domain: {raw!r}") from exc
    if len(domain) > MAX_DOMAIN_LEN:
        raise ValueError(f"domain is longer than {MAX_DOMAIN_LEN} characters")
    labels = domain.split(".")
    if len(labels) < 2:
        raise ValueError(f"domain must have at least one dot: {raw!r}")
    for label in labels:
        if not _LABEL_RE.match(label):
            raise ValueError(f"invalid domain label {label!r} in {raw!r}")
    if labels[-1].isdigit():
        raise ValueError(f"IP addresses are not accepted as a domain: {raw!r}")
    return domain


def parse_request(text: str) -> dict:
    """Parse the JSON request. Returns a dict with keys company, domain,
    context (all str). Raises ValueError with a message
    a human can act on. Unknown keys are ignored."""
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            'request must be a JSON object like {"company": "...", "domain": "..."}'
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object, not " + type(data).__name__)

    company = data.get("company")
    if not isinstance(company, str) or not company.strip():
        raise ValueError("company is required and must be a non-empty string")
    if "domain" not in data:
        raise ValueError("domain is required")

    context = data.get("context")
    if context is not None and not isinstance(context, str):
        raise ValueError("context must be a string")

    return {
        "company": company.strip(),
        "domain": normalize_domain(data["domain"]),
        "context": (context or "").strip(),
    }


def format_request(req: dict) -> str:
    """Text for state["request"], used in agent instructions."""
    lines = [f"Company: {req['company']}", f"Domain: {req['domain']}"]
    if req.get("context"):
        lines.append(f"Context: {req['context']}")
    return "\n".join(lines)
