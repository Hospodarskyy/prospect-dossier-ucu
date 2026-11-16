"""Offline tests for dossier_agent/request.py and init_state."""
import json
from types import SimpleNamespace

import pytest
from google.genai import types

from dossier_agent.agent import init_state
from dossier_agent.request import format_request, normalize_domain, parse_request


# --------------------------------------------------------------------------
# normalize_domain
# --------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    "plausible.io",
    "Plausible.IO",
    "  plausible.io  ",
    "plausible.io.",
    "www.plausible.io",
    "https://www.plausible.io/",
    "http://plausible.io/about?x=1#team",
    "plausible.io:443",
    "HTTPS://WWW.PLAUSIBLE.IO:8080/a/b",
    "plausible.io/../../etc",          # path is dropped, never used
])
def test_normalize_domain_spellings(raw):
    assert normalize_domain(raw) == "plausible.io"


@pytest.mark.parametrize("raw,expected", [
    ("sub.example.co.uk", "sub.example.co.uk"),
    ("my-company.com", "my-company.com"),
    ("münchen.de", "xn--mnchen-3ya.de"),
    ("www.www.example.com", "www.example.com"),   # only one "www." is removed
])
def test_normalize_domain_valid(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "https://",
    "localhost",
    "../../config",
    "..",
    "a..b.com",
    ".example.com",
    "a b.com",
    "user@evil.com",
    "https://user:pass@evil.com/",
    "-bad.com",
    "bad-.com",
    "evil.com\\x",
    "evil.com\x00",
    "evil_name.com",
    "a" * 64 + ".com",
    ("a" * 60 + ".") * 5 + "com",       # longer than 253
    "192.168.0.1",
    "example.com:abc",
])
def test_normalize_domain_rejects(raw):
    with pytest.raises(ValueError):
        normalize_domain(raw)


@pytest.mark.parametrize("raw", [None, 123, ["plausible.io"]])
def test_normalize_domain_rejects_non_string(raw):
    with pytest.raises(ValueError):
        normalize_domain(raw)


# --------------------------------------------------------------------------
# parse_request
# --------------------------------------------------------------------------
def _req(**fields) -> str:
    return json.dumps(fields)


def test_parse_full_request():
    req = parse_request(_req(
        company="  Plausible Analytics ",
        domain="https://www.Plausible.io/",
        context=" Looking for ClickHouse help ",
    ))
    assert req == {
        "company": "Plausible Analytics",
        "domain": "plausible.io",
        "context": "Looking for ClickHouse help",
    }


def test_parse_minimal_request_defaults():
    req = parse_request(_req(company="Plausible Analytics", domain="plausible.io"))
    assert req["context"] == ""


def test_parse_null_context():
    req = parse_request(_req(company="X", domain="x.com", context=None))
    assert req["context"] == ""


@pytest.mark.parametrize("extra", [{"extra": "ignored"}, {"requester_chat_id": "123"}])
def test_parse_ignores_unknown_keys(extra):
    req = parse_request(_req(company="X", domain="x.com", **extra))
    assert set(req) == {"company", "domain", "context"}


@pytest.mark.parametrize("text", [
    "",
    "Company: Plausible Analytics, domain: plausible.io.",   # old free-text input
    "{not json",
    "[]",
    '"plausible.io"',
    "null",
    _req(domain="plausible.io"),
    _req(company="", domain="plausible.io"),
    _req(company="   ", domain="plausible.io"),
    _req(company=42, domain="plausible.io"),
    _req(company="X"),
    _req(company="X", domain="../../config"),
    _req(company="X", domain="x.com", context=["a"]),
])
def test_parse_rejects(text):
    with pytest.raises(ValueError):
        parse_request(text)


def test_format_request():
    base = {"company": "Plausible Analytics", "domain": "plausible.io"}
    assert format_request({**base, "context": ""}) == \
        "Company: Plausible Analytics\nDomain: plausible.io"
    assert format_request({**base, "context": "Why now"}).endswith("\nContext: Why now")


# --------------------------------------------------------------------------
# init_state (fake CallbackContext: only .state and .user_content are used)
# --------------------------------------------------------------------------
def _ctx(text: str | None, state: dict | None = None):
    content = None if text is None else types.Content(
        role="user", parts=[types.Part(text=text)])
    return SimpleNamespace(state=state if state is not None else {}, user_content=content)


def test_init_state_valid_request():
    ctx = _ctx(_req(company="Plausible Analytics", domain="www.plausible.io"))
    assert init_state(ctx) is None
    s = ctx.state
    assert s["domain"] == "plausible.io"
    assert s["company"] == "Plausible Analytics"
    assert s["request"] == "Company: Plausible Analytics\nDomain: plausible.io"
    assert s["input_error"] == ""
    assert "today" in s and len(s["seller_cases"]) == 6 and s["loaded_cases"] == []


def test_init_state_retry_after_invalid_request():
    state = {}
    assert init_state(_ctx("not json", state)) is not None
    assert state["input_error"]
    assert init_state(_ctx(_req(company="X", domain="x.com"), state)) is None
    assert state["input_error"] == ""
    assert state["domain"] == "x.com"


@pytest.mark.parametrize("text", [None, "", "Company: X, domain: x.com"])
def test_init_state_invalid_request_stops_run(text):
    ctx = _ctx(text)
    result = init_state(ctx)
    assert isinstance(result, types.Content)
    assert result.parts[0].text.startswith("Invalid request:")
    assert ctx.state["input_error"]
    assert "request" not in ctx.state


def test_init_state_keeps_existing_request():
    state = {"request": "Company: A\nDomain: a.com", "domain": "a.com"}
    ctx = _ctx("this second message is not JSON", state)
    assert init_state(ctx) is None
    assert state["request"] == "Company: A\nDomain: a.com"
    assert state["domain"] == "a.com"
