"""Offline tests for dossier_agent/format_check.py."""
import importlib.util
from functools import partial
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parent.parent
          / "dossier_agent" / "format_check.py")
spec = importlib.util.spec_from_file_location("check_dossier_format", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ANGLE = "Metacortex angle"
check = partial(m.check_dossier_format, angle_section=ANGLE)
check_urls = partial(m.check_dossier_urls, angle_section=ANGLE)

GOOD = """# Plausible Analytics

## Snapshot
- Team of 11. (https://plausible.io/about)

## Recent news
- [Pending]

## Tech signals
- Uses Elixir. (https://plausible.io/blog/tech)

## Key people
- Uku Taht, Design and development (https://plausible.io/about)

## Likely pains
- Hit limits of vertical scaling. (https://plausible.io/jobs)
- Hypothesis: self-hosted ClickHouse is an operational burden (based on: limits of vertical scaling) (https://plausible.io/jobs)

## Metacortex angle
- A managed warehouse removes the scaling work (based on: limits of vertical scaling).
- Question: how much engineering time goes into ClickHouse today?

## What changed
- [Pending]
"""


def test_good_dossier_passes():
    assert check(GOOD) == {"success": True, "message": "Format is valid."}


def test_note_line_under_title_is_allowed():
    md = GOOD.replace("# Plausible Analytics\n",
                      "# Plausible Analytics\nNote: the research did not fully pass verification.\n")
    assert check(md)["success"]


def test_missing_title_fails():
    assert "title" in check(GOOD.replace("# Plausible Analytics\n", ""))["message"]


def test_random_text_before_first_section_fails():
    md = GOOD.replace("# Plausible Analytics\n", "# Plausible Analytics\nSome intro text.\n")
    assert not check(md)["success"]


def test_two_note_lines_fail():
    md = GOOD.replace("# Plausible Analytics\n", "# Plausible Analytics\nNote: a\nNote: b\n")
    assert not check(md)["success"]


def test_missing_section_fails():
    md = GOOD.replace("## What changed\n- [Pending]\n", "")
    assert "What changed" in check(md)["message"]


def test_wrong_order_fails():
    md = GOOD.replace("## Snapshot", "## TMP").replace("## Recent news", "## Snapshot") \
             .replace("## TMP", "## Recent news")
    assert "order" in check(md)["message"]


def test_empty_section_fails():
    md = GOOD.replace("## Recent news\n- [Pending]\n", "## Recent news\n\n")
    assert "Recent news" in check(md)["message"]


def test_fact_without_url_fails():
    md = GOOD.replace("- Uses Elixir. (https://plausible.io/blog/tech)", "- Uses Elixir.")
    result = check(md)
    assert not result["success"] and "Tech signals" in result["message"]


@pytest.mark.parametrize("section", [ANGLE, "What changed"])
def test_reasoning_sections_need_no_url(section):
    assert check(GOOD)["success"]
    md = GOOD.replace(f"## {section}\n", f"## {section}\n- An idea without a URL.\n")
    assert check(md)["success"]


def test_hypothesis_without_evidence_url_fails():
    md = GOOD.replace(" (based on: limits of vertical scaling) (https://plausible.io/jobs)",
                      " (based on: limits of vertical scaling)")
    result = check(md)
    assert not result["success"] and "hypothesis" in result["message"]


def test_too_long_dossier_fails():
    filler = "".join(f"- Fact number {i} about the company. (https://plausible.io/about)\n"
                     for i in range(200))
    md = GOOD.replace("## Tech signals", filler + "\n## Tech signals")
    result = check(md)
    assert not result["success"] and "too long" in result["message"]


def test_dossier_at_word_limit_passes():
    words = len(GOOD.split())
    md = GOOD.replace("## What changed\n- [Pending]",
                      "## What changed\n- " + "word " * (m.MAX_WORDS - words + 1))
    assert len(md.split()) == m.MAX_WORDS
    assert check(md)["success"]


def test_empty_input_fails():
    assert not check("")["success"]


# ------------------------------------------------- URL provenance
RESEARCH = """## Snapshot
- Team of 11. (source: https://plausible.io/about) (quote: "team of 11")
- Uses Elixir. (source: https://plausible.io/blog/tech) (quote: "Elixir")
- Hit limits. (source: https://plausible.io/jobs) (quote: "limits")
- Wiki. (source: https://en.wikipedia.org/wiki/Hello_(company)) (quote: "x")
"""
CASES = {"https://example.com/case-studies/event-analytics-scaling"}


def test_urls_from_research_and_cases_pass():
    md = GOOD.replace(
        "- Question: how much engineering time goes into ClickHouse today?",
        "- See our case (https://example.com/case-studies/event-analytics-scaling).",
    )
    assert check_urls(md, RESEARCH, CASES)["success"]


def test_invented_fact_url_fails():
    md = GOOD.replace("https://plausible.io/about)", "https://plausible.io/team-page)", 1)
    result = check_urls(md, RESEARCH, CASES)
    assert not result["success"]
    assert "Snapshot" in result["message"] and "team-page" in result["message"]


def test_invented_case_study_url_fails():
    md = GOOD.replace("## What changed", "- Case (https://example.com/case-studies/fake).\n\n## What changed")
    result = check_urls(md, RESEARCH, CASES)
    assert not result["success"] and "load_seller_cases" in result["message"]


def test_url_with_parentheses_matches():
    md = GOOD.replace("https://plausible.io/about)", "https://en.wikipedia.org/wiki/Hello_(company))", 1)
    assert check_urls(md, RESEARCH, CASES)["success"]


def test_without_seller_file_angle_must_have_no_urls():
    md = GOOD.replace("## What changed", "- Case (https://example.com/x).\n\n## What changed")
    assert not check_urls(md, RESEARCH, set())["success"]
    assert check_urls(GOOD, RESEARCH, set())["success"]

# ------------------------------------------------- item 5
def test_key_people_needs_job_title():
    md = GOOD.replace("- Uku Taht, Design and development (https://plausible.io/about)",
                      "- Uku Taht (https://plausible.io/about)")
    result = check(md)
    assert not result["success"] and "Key people" in result["message"]


def test_key_people_pending_is_fine():
    md = GOOD.replace("- Uku Taht, Design and development (https://plausible.io/about)", "- [Pending]")
    assert check(md)["success"]


def test_at_most_five_hypotheses():
    h = "- Hypothesis: pain {i} (based on: limits) (https://plausible.io/jobs)\n"
    five = "".join(h.format(i=i) for i in range(4))   # GOOD already has one
    assert check(GOOD.replace("## Metacortex angle", five + "\n## Metacortex angle"))["success"]
    six = "".join(h.format(i=i) for i in range(5))
    result = check(GOOD.replace("## Metacortex angle", six + "\n## Metacortex angle"))
    assert not result["success"] and "6 hypotheses" in result["message"]


@pytest.mark.parametrize("heading", ["## Your angle", "## Seller angle", "## metacortex angle"])
def test_other_angle_heading_fails(heading):
    result = check(GOOD.replace("## Metacortex angle", heading))
    assert not result["success"] and "Metacortex angle" in result["message"]


def test_angle_heading_follows_the_seller():
    md = GOOD.replace("## Metacortex angle", "## Initech angle")
    assert m.check_dossier_format(md, angle_section="Initech angle")["success"]
    assert not check(md)["success"]
