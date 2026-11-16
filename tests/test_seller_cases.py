"""Offline tests for config/seller_cases.md and the load_seller_cases tool."""
import json
from types import SimpleNamespace

import pytest
from google.genai import types

from dossier_agent.agent import init_state, load_seller_cases
from dossier_agent.seller_cases import (
    CASES_KEY, MAX_CANDIDATES, ConfigError, angle_section, load_cases_file, parse_seller_cases,
    _words, industry_groups, parse_seller_name, select_candidates,
)
from dossier_agent.format_check import check_dossier_urls

ONE_CASE = """# Seller: Metacortex

## cs-01: Scaling an event-analytics pipeline
- Industry: SaaS
- Technologies: ClickHouse, Kafka,  Kubernetes ,Python
- Problem: Single-node analytics database hit limits as event volume grew.
- Result: Moved to a horizontally scaled ingestion and storage setup.
- URL: https://example.com/case-studies/event-analytics-scaling
"""


# --------------------------------------------------------------------------
# seller name, parse_seller_cases, load_cases_file
# --------------------------------------------------------------------------
def test_seller_name_and_angle_section():
    assert parse_seller_name(ONE_CASE) == "Metacortex"
    assert parse_seller_name("\n\n#  Seller:  Pied Piper  \n") == "Pied Piper"
    assert angle_section("Metacortex") == "Metacortex angle"


@pytest.mark.parametrize("first_line", [
    "# Metacortex case studies",            # no "Seller:"
    "## Seller: Metacortex",                # wrong level
    "# Seller:",                            # empty name
    "# Seller: Meta<b>cortex</b>",          # markup
    "# Seller: " + "x" * 61,                # too long
    "# Seller: -dash first",
])
def test_bad_seller_line_is_config_error(first_line):
    with pytest.raises(ConfigError):
        parse_seller_name(ONE_CASE.replace("# Seller: Metacortex", first_line))


def test_seller_line_must_come_first():
    with pytest.raises(ConfigError):
        parse_seller_name("Intro text\n" + ONE_CASE)


def test_parse_one_case():
    assert parse_seller_cases(ONE_CASE) == [{
        "id": "cs-01", "title": "Scaling an event-analytics pipeline", "industry": "SaaS",
        "technologies": ["ClickHouse", "Kafka", "Kubernetes", "Python"],
        "problem": "Single-node analytics database hit limits as event volume grew.",
        "result": "Moved to a horizontally scaled ingestion and storage setup.",
        "url": "https://example.com/case-studies/event-analytics-scaling",
    }]


def test_parse_ignores_unknown_fields_and_text_outside_sections():
    md = "- URL: https://outside.example\n" + ONE_CASE + "- Client: Secret Corp\nsome text\n"
    cases = parse_seller_cases(md)
    assert len(cases) == 1 and "client" not in cases[0]


def test_parse_demo_file(tmp_storage):
    seller, cases = load_cases_file(tmp_storage)
    assert seller == "Metacortex"
    assert [c["id"] for c in cases] == ["cs-01", "cs-02", "cs-03", "cs-04", "cs-05", "cs-06"]
    assert all(c["url"].startswith("https://example.com/") for c in cases)


@pytest.mark.parametrize("md", [
    ONE_CASE.replace("- URL: https://example.com/case-studies/event-analytics-scaling\n", ""),
    ONE_CASE.replace("https://example.com", "example.com"),
    ONE_CASE + ONE_CASE,                                        # duplicate id
])
def test_parse_rejects_bad_cases(md):
    with pytest.raises(ConfigError):
        parse_seller_cases(md)


def test_missing_file_is_config_error(tmp_storage):
    tmp_storage.write_text(CASES_KEY, "# Seller: Metacortex\n")     # no cases
    with pytest.raises(ConfigError, match="no case studies"):
        load_cases_file(tmp_storage)
    tmp_storage.write_text(CASES_KEY, "")                             # empty file
    with pytest.raises(ConfigError, match="Seller"):
        load_cases_file(tmp_storage)
    (tmp_storage.root / CASES_KEY).unlink()
    with pytest.raises(ConfigError, match="not found"):
        load_cases_file(tmp_storage)


# --------------------------------------------------------------------------
# select_candidates
# --------------------------------------------------------------------------
@pytest.fixture
def cases(tmp_storage):
    return load_cases_file(tmp_storage)[1]


def test_candidates_put_matches_first(cases):
    ids = [c["id"] for c in select_candidates(cases, "SaaS", ["ClickHouse", "Hetzner"])]
    assert ids[:2] == ["cs-01", "cs-03"]          # SaaS + ClickHouse, SaaS + Hetzner
    assert len(ids) == MAX_CANDIDATES


def test_candidates_match_pain_words_in_problem(cases):
    ids = [c["id"] for c in select_candidates(cases, "", ["chargebacks"])]
    assert ids[0] == "cs-04"


def test_candidates_without_match_keep_file_order(cases):
    ids = [c["id"] for c in select_candidates(cases, "Agriculture", ["COBOL"])]
    assert ids == ["cs-01", "cs-02", "cs-03", "cs-04", "cs-05"]


@pytest.mark.parametrize("tech", [None, [], ["", "  ", "!!!"], [1, None]])
def test_candidates_tolerate_bad_tech(cases, tech):
    assert len(select_candidates(cases, "SaaS", tech)) == MAX_CANDIDATES


# found by the component eval (2026-11-13): Doctolib got industry "Healthcare",
# and cs-06 (HealthTech) was not even in the top 5
@pytest.mark.parametrize("industry,first", [
    ("Healthcare", "cs-06"), ("Digital health", "cs-06"), ("MedTech", "cs-06"),
    ("Retail", "cs-04"), ("Online retail", "cs-04"), ("ecommerce", "cs-04"),
])
def test_industry_synonyms(cases, industry, first):
    assert select_candidates(cases, industry, [])[0]["id"] == first


def test_industry_groups():
    assert industry_groups("Healthcare SaaS") == {"healthtech", "saas"}
    assert industry_groups("E-commerce") == {"e-commerce"}
    assert industry_groups("Agriculture") == {"agriculture"}       # unknown: itself
    assert industry_groups("") == set()


def test_words_drop_trailing_dots_but_keep_inner_ones():
    assert _words("Rising chargebacks from fraudulent card payments.") >= {"payments"}
    assert "node.js" in _words("Built with Node.js.")


def test_candidates_match_a_phrase_at_the_end_of_a_sentence(cases):
    # "card payments" is the end of cs-04's problem sentence ("... card payments.")
    assert select_candidates(cases, "", ["card payments"])[0]["id"] == "cs-04"



# --------------------------------------------------------------------------
# init_state: the file is required
# --------------------------------------------------------------------------
REQ = json.dumps({"company": "Plausible Analytics", "domain": "plausible.io"})


def _init(state):
    ctx = SimpleNamespace(state=state, user_content=types.Content(
        role="user", parts=[types.Part(text=REQ)]))
    return init_state(ctx)


def test_init_state_loads_cases():
    state = {}
    assert _init(state) is None
    assert len(state["seller_cases"]) == 6
    assert state["seller"] == "Metacortex" and state["angle_section"] == "Metacortex angle"
    assert state["loaded_cases"] == [] and state["case_study_urls"] == []


def test_init_state_fails_without_case_file(tmp_storage):
    (tmp_storage.root / CASES_KEY).unlink()
    with pytest.raises(ConfigError):
        _init({})


def test_invalid_request_is_reported_before_config_check(tmp_storage):
    (tmp_storage.root / CASES_KEY).unlink()
    ctx = SimpleNamespace(state={}, user_content=types.Content(
        role="user", parts=[types.Part(text="not json")]))
    assert init_state(ctx) is not None          # input error, not ConfigError


# --------------------------------------------------------------------------
# load_seller_cases tool: only returned cases may be cited
# --------------------------------------------------------------------------
def _tool_ctx(cases):
    return SimpleNamespace(state={"seller_cases": cases, "loaded_cases": [], "case_study_urls": []})


def test_tool_returns_candidates_and_records_them(cases):
    ctx = _tool_ctx(cases)
    out = load_seller_cases("SaaS", ["ClickHouse"], ctx)
    assert out["success"] is True and len(out["cases"]) == MAX_CANDIDATES
    assert out["cases"][0]["id"] == "cs-01"
    assert ctx.state["case_study_urls"] == [c["url"] for c in out["cases"]]


def test_second_call_adds_without_duplicates(cases):
    ctx = _tool_ctx(cases)
    load_seller_cases("SaaS", ["ClickHouse"], ctx)
    second = load_seller_cases("HealthTech", ["Gemini"], ctx)
    assert second["cases"][0]["id"] == "cs-06"
    urls = ctx.state["case_study_urls"]
    assert len(urls) == len(set(urls)) == 6     # 5 + the one not returned before


def test_url_check_allows_only_returned_cases(cases):
    ctx = _tool_ctx(cases[:2])                  # the tool can only return cs-01, cs-02
    load_seller_cases("SaaS", [], ctx)
    allowed = set(ctx.state["case_study_urls"])
    md = ("# X\n\n## Metacortex angle\n"
          "- Case (https://example.com/case-studies/event-analytics-scaling)\n")
    assert check_dossier_urls(md, "", allowed, angle_section="Metacortex angle")["success"]
    md_other = md.replace("event-analytics-scaling", "fraud-detection")   # cs-04: in file, not returned
    result = check_dossier_urls(md_other, "", allowed, angle_section="Metacortex angle")
    assert not result["success"] and "load_seller_cases" in result["message"]
