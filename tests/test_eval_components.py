"""Component evaluation (eval/): metric formulas and every module on a small
made-up run. Offline: no model, no network."""
import json
import random

from eval.build_verifier_set import change_number, sentences, subtle, swap_words
from eval.components import (case_selection, memory, request_parsing, researcher,
                             source_verifier, system, writer)
from eval.components.common import Run, dossier_sections, fmt, load_runs, prf, strip_urls

PAGE_TEXT = ("Acme Analytics is a privacy-first web analytics company based in Tallinn, "
             "Estonia. The team of 12 people serves 5,000 paying customers from its "
             "own servers. Published on 2026-10-01 by the Acme team.")


def _fact(section, claim, status="supported", url="https://acme.io/about", weak=False,
          date=None, date_check=None):
    return {"section": section, "claim": claim, "url": url, "final_url": url, "status": status,
            "weak_support": weak, "date": date, "date_check": date_check}


REPORT = """# Acme Analytics

## Snapshot
- Acme Analytics is a privacy-first web analytics company based in Tallinn. (https://acme.io/about)
- Acme is the biggest analytics vendor in the world. (https://acme.io/about)

## Recent news
- [Pending]

## Tech signals
- Acme runs on Kubernetes clusters. (https://acme.io/jobs)

## Key people
- [Pending]

## Likely pains
- Hypothesis: Scaling servers is hard for a small team. (based on: team of 12) (https://acme.io/about)

## Metacortex angle
- Metacortex scaled an event pipeline (https://example.com/case-studies/event-analytics-scaling).

## What changed
- [Pending]

## Sources
- https://acme.io/about
"""


def _run(tmp_path, **spec_extra):
    spec = {"id": "acme", "request": {"company": "Acme", "domain": "acme.io"}, "kind": "real",
            "seed_memory": False, "relevant_cases": ["cs-01"], **spec_extra}
    facts = [
        _fact("Snapshot", "Acme Analytics is a privacy-first web analytics company based in "
                          "Tallinn, Estonia."),
        _fact("Snapshot", "The team has 12 people.", weak=True),
        _fact("Recent news", "Acme launched v2.", status="not_found", date="2026-10-20"),
        _fact("Tech signals", "Acme uses Kubernetes.", status="unreachable",
              url="https://acme.io/jobs"),
    ]
    folder = tmp_path / "runs" / "acme"
    folder.mkdir(parents=True)
    result = {"run_id": "r1", "status": "ok", "started_at": "2026-11-13T10:00:00+00:00",
              "usage": {"llm_calls": 6, "searches": 4, "cost_usd": 0.12,
                        "elapsed_seconds": 150.0, "hard_stop": None, "research_stop": None},
              "data": {"company": "Acme", "domain": "acme.io", "iterations": 2,
                       "seller": "Metacortex", "previous_dossier_date": "",
                       "seller_cases": [{"id": "cs-01", "title": "Event analytics",
                                         "url": "https://example.com/case-studies/"
                                                "event-analytics-scaling"}]}}
    trace = {"iterations": [
        {"iteration": 1, "research": "Searches performed: 3\n- x (source: https://acme.io/about)",
         "verification_counts": {"supported": 1, "not_found": 1}, "facts": facts[:1] + facts[2:3],
         "judge_feedback": {"status": "fail"}},
        {"iteration": 2, "research": "Searches performed: 2\n- y (source: https://acme.io/about)",
         "verification_counts": {"supported": 2, "pending": 1}, "facts": facts,
         "judge_feedback": {"status": "pass"}},
    ]}
    calls = {"calls": [
        {"type": "call", "name": "load_seller_cases",
         "args": {"industry": "SaaS", "tech": ["ClickHouse"]}},
        {"type": "response", "name": "load_seller_cases", "case_ids": ["cs-01", "cs-02"]},
        {"type": "response", "name": "check_dossier_format", "success": False},
        {"type": "response", "name": "check_dossier_format", "success": True},
    ]}
    (folder / "result.json").write_text(json.dumps(result))
    (folder / "trace.json").write_text(json.dumps(trace))
    (folder / "calls.json").write_text(json.dumps(calls))
    (folder / "report.md").write_text(REPORT)
    (folder / "memory.json").write_text(json.dumps({"run_id": "r1"}))
    return load_runs(tmp_path / "runs", [spec])


# --------------------------------------------------------------------------
# common
# --------------------------------------------------------------------------
def test_prf_and_undefined_values():
    assert prf(8, 2, 0) == {"precision": 0.8, "recall": 1.0, "f1": 0.889, "tp": 8, "fp": 2, "fn": 0}
    assert prf(0, 0, 0)["precision"] is None and prf(0, 0, 0)["f1"] is None


def test_fmt_and_strip_urls():
    assert [fmt(None), fmt(True), fmt(1.0), fmt(0.125), fmt("a|b")] == ["—", "yes", "1", "0.125",
                                                                         "a\\|b"]
    assert strip_urls("- Acme is in Tallinn. (https://acme.io/about)") == "Acme is in Tallinn."


def test_load_runs_keeps_the_order_of_companies_and_skips_missing(tmp_path):
    runs = _run(tmp_path)
    assert [r.id for r in runs] == ["acme"]
    assert load_runs(tmp_path / "runs", [{"id": "missing"}]) == []
    assert dossier_sections(REPORT)["Recent news"] == ["- [Pending]"]


# --------------------------------------------------------------------------
# components on the made-up run
# --------------------------------------------------------------------------
def test_researcher_metrics(tmp_path):
    m = researcher.evaluate(_run(tmp_path))["metrics"]
    assert m["grounded rate, 1st iteration (supported / checkable)"] == 0.5
    # final: 2 supported of 3 checkable (the unreachable page is not the researcher's fault)
    assert m["grounded rate, final iteration"] == 0.667
    assert m["weak support (share of supported facts)"] == 0.5
    assert m["misquote rate (quote not on the page)"] == 0.333
    assert m["unreachable pages (excluded above)"] == 0.25
    assert m["section coverage (mean share of the 5 fact sections with a supported fact)"] == 0.2


def test_researcher_counts_invented_facts_of_a_fictional_company(tmp_path):
    m = researcher.evaluate(_run(tmp_path, kind="fictional"))["metrics"]
    assert m["fictional company: facts with a source (target 0)"] == 6


def test_writer_bullets_honesty_and_cases(tmp_path):
    result = writer.evaluate(_run(tmp_path))
    m, row = result["metrics"], result["rows"][0]
    assert m["format valid"] == 1.0
    assert m["format valid at the first check_dossier_format call"] == 0.0
    # the Snapshot bullets: one faithful, one rewritten; Tech signals cites an unreachable page
    assert row["faithful bullets"] == "1/3"
    assert "rewritten 1" in row["other bullets"] and "unverified source 1" in row["other bullets"]
    assert m["hypotheses based on a supported fact"] == 1.0
    # Tech signals has content but no supported fact in the research
    assert m["sections with facts but no supported research"] == 1
    assert m["cited case studies: precision (relevant / cited)"] == 1.0
    assert m["cited case studies all returned by load_seller_cases"] == 1.0


def test_writer_fictional_company_must_cite_no_case(tmp_path):
    m = writer.evaluate(_run(tmp_path, kind="fictional", relevant_cases=[]))["metrics"]
    assert m["no case cited when none fits (fictional company)"] == 0.0


def test_memory_first_request_and_repeat(tmp_path):
    first = memory.evaluate(_run(tmp_path))
    assert first["metrics"]["first requests: What changed correctly [Pending]"] == 1.0
    assert first["metrics"]["finished runs that saved their memory"] == 1.0
    repeat = memory.check(Run(id="x", spec={"seed_memory": True}, result={
        "run_id": "r2", "data": {"previous_dossier_date": "2026-11-12"}},
        report="## What changed\n- No material changes since 2026-11-12.\n",
        memory={"run_id": "r2"}))
    assert repeat["ok"] and repeat["memory saved"]
    bad = memory.check(Run(id="x", spec={"seed_memory": True}, result={
        "run_id": "r2", "data": {"previous_dossier_date": "2026-11-12"}},
        report="## What changed\n- Updated the Snapshot section.\n"))
    assert not bad["ok"] and not bad["memory saved"]


def test_system_metrics(tmp_path):
    m = system.evaluate(_run(tmp_path))["metrics"]
    assert m["status ok"] == 1.0 and m["judge passed at the 1st iteration"] == 0.0
    assert m["mean research iterations"] == 2 and m["runs within $0.40"] == 1.0


def test_case_selection_rank_and_real_arguments(tmp_path):
    assert case_selection.rank_of_first(["cs-02", "cs-01"], {"cs-01"}) == 2
    assert case_selection.rank_of_first(["cs-02"], {"cs-01"}) is None
    result = case_selection.evaluate(_run(tmp_path))
    assert result["metrics"]["eval runs: inputs"] == 1
    assert result["metrics"]["profiles: inputs"] == 10


def test_request_parsing_set_is_fully_correct():
    m = request_parsing.evaluate()["metrics"]
    assert m["cases"] >= 15 and m["accuracy"] == 1.0


# --------------------------------------------------------------------------
# SourceVerifier cases
# --------------------------------------------------------------------------
PAGE = {"id": "p1", "url": "https://acme.io/about", "text": PAGE_TEXT}
SENTENCE = "The team of 12 people serves 5,000 paying customers from its own servers."


def _case(variant, claim, quote, status, weak=None, date=None, expect_date=None):
    return {"id": variant, "variant": variant, "page": "p1", "claim": claim, "quote": quote,
            "date": date, "expect_status": status, "expect_weak": weak,
            "expect_date": expect_date, "source": "synthetic"}


def test_verifier_cases_by_construction():
    exact = source_verifier.run_case(_case("exact", SENTENCE, SENTENCE, "supported", False), PAGE)
    assert exact["ok"] and exact["got"] == "supported"
    swapped = swap_words(SENTENCE, random.Random(1))
    assert source_verifier.run_case(_case("word_swap", SENTENCE, swapped, "not_found"), PAGE)["ok"]
    changed = change_number(SENTENCE)
    number = source_verifier.run_case(_case("number_changed", changed, SENTENCE, "supported",
                                            True), PAGE)
    assert number["got"] == "supported + weak" and number["ok"]
    dated = source_verifier.run_case(_case("date_on_page", SENTENCE, SENTENCE, "supported", False,
                                           "2026-10-01", "exact"), PAGE)
    assert dated["ok"]


def test_build_helpers():
    assert sentences("Short one. " + SENTENCE + " Tiny.") == [SENTENCE]
    assert subtle("Acme is a small analytics tool.") == \
        "Acme is the largest and fastest-growing small analytics tool."
    assert change_number("We have 12 people.") == "We have 43 people."
    assert change_number("No numbers here.") is None
