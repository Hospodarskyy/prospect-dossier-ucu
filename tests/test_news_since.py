"""Offline tests: which news is new since the previous dossier (What changed)."""
from types import SimpleNamespace

import pytest

from dossier_agent import agent as agent_module
from dossier_agent.agent import prepare_writer
from dossier_agent.instructions import WRITER_INSTRUCTION
from dossier_agent.memory import format_news_since, news_since

RESEARCH = """Searches performed: 5
## Snapshot
- Team of 11. (source: https://a.example/about) (quote: "team of 11")
## Recent News (Last 90 Days)
- Released version 3.0. (date: 2026-11-12) (source: https://a.example/v3) (quote: "3.0")
- Community Edition 3.2.1 security patch. (date: 2026-10-02) (source: https://a.example/ce) (quote: "3.2.1")
- Same-day post. (date: 2026-11-09) (source: https://a.example/same) (quote: "same")
- Post with a bad date. (date: soon) (source: https://a.example/bad) (quote: "bad")
- [Pending] no data found
## Business pains
- Hypothesis: x (based on: y)
"""


def test_only_news_after_the_previous_dossier_is_new():
    assert news_since(RESEARCH, "2026-11-09") == [
        {"claim": "Released version 3.0.", "date": "2026-11-12", "url": "https://a.example/v3"}]


def test_the_case_from_the_service_run_is_not_new():
    # 7b: news from 2026-10-02 with a previous dossier from 2026-11-09, and a
    # same-day post: neither is new
    dates = [n["date"] for n in news_since(RESEARCH, "2026-11-09")]
    assert "2026-10-02" not in dates and "2026-11-09" not in dates


@pytest.mark.parametrize("since", ["", None, "yesterday"])
def test_without_a_valid_previous_date_nothing_is_new(since):
    assert news_since(RESEARCH, since) == []


def test_section_name_variants():
    research = "## Recent news\n- A. (date: 2026-12-01) (source: https://x.example) (quote: \"a\")\n"
    assert len(news_since(research, "2026-11-09")) == 1


def test_format_news_since():
    news = news_since(RESEARCH, "2026-11-09")
    assert format_news_since(news, "2026-11-09") == "- Released version 3.0. (date: 2026-11-12)"
    assert format_news_since([], "2026-11-09") == \
        "None: no news item in RESEARCH is dated after 2026-11-09."
    assert format_news_since([], "") == ""                # no previous dossier


def test_prepare_writer_sets_new_news():
    state = {"research": RESEARCH, "previous_dossier_date": "2026-11-09"}
    prepare_writer(SimpleNamespace(state=state))
    assert state["new_news"] == "- Released version 3.0. (date: 2026-11-12)"


def test_prepare_writer_without_previous_dossier():
    state = {"research": RESEARCH, "previous_dossier_date": ""}
    prepare_writer(SimpleNamespace(state=state))
    assert state["new_news"] == ""


def test_writer_wiring():
    assert agent_module.writer.before_agent_callback is prepare_writer
    assert "{new_news?}" in WRITER_INSTRUCTION
    assert "Only the news listed there are new" in WRITER_INSTRUCTION


def test_writer_instruction_people_rule():
    """A different sample of Key people is not a change (CHI run 90d109de: "Sanne -> Bogdan")."""
    assert "no longer listed" not in WRITER_INSTRUCTION
    assert "A different set of people in Key" in WRITER_INSTRUCTION
