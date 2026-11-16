"""Offline tests for dossier_agent/verification.py (no network, no ADK)."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

# Load by path: importing the dossier_agent package would import ADK and agent.py.
MODULE_PATH = Path(__file__).resolve().parent.parent / "dossier_agent" / "verification.py"
spec = importlib.util.spec_from_file_location("verification", MODULE_PATH)
v = importlib.util.module_from_spec(spec)
sys.modules["verification"] = v      # needed by @dataclass with postponed annotations
spec.loader.exec_module(v)

GOOGLE_URL = (
    "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
    "AUZIYQH1FdUNl2HC-wrCI011rGzHJYMM0ZYtFhaMqJoJ3AXcfUWxdTOuRdglplygp3Osgg8x=="
)
WIKI_URL = "https://en.wikipedia.org/wiki/Hello_(company)"
QUOTE = (
    "Hello was an American technology company that sold sleep tracking "
    "devices and a sleep tracking application to help monitor sleep."
)
PAGE = (
    "Hello Inc. Type Private Industry Health technology , sleep tracking "
    "founded August 28, 2012 dissolved June 2017 headquarters San Francisco "
    ", California, US [ 1 ] CEO James Proud . Hello was an American technology "
    "company that sold sleep tracking devices and a sleep tracking application "
    "to help monitor sleep . [ 2 ]"
)

RESEARCH = f"""Searches performed: 2 (queries: hello sleep; hello ceo)

## Snapshot
- Hello sold sleep trackers. (source: {GOOGLE_URL}) (quote: "{QUOTE}")

## Recent news
- Raised a seed round. (date: 2026-09-15) (source: https://news.example.com/seed) (quote: "raised a seed round")

## Tech signals
- [Pending] no data found

## Key people
- James Proud: CEO. (source: {WIKI_URL}) (quote: "CEO James Proud")

## Business pains
- Burned cash on free cloud. (source: https://example.com/a) (quote: "burned cash")
- Hypothesis: Financial strain. (based on: burned cash)
"""


# ---------------------------------------------------------------- parser
def test_parses_fact_with_redirect_url_and_quote():
    facts = v.parse_research(RESEARCH)
    first = facts[0]
    assert first.kind == "fact"
    assert first.section == "Snapshot"
    assert first.claim == "Hello sold sleep trackers."
    assert first.url == GOOGLE_URL
    assert first.quote == QUOTE
    assert first.date is None


def test_parses_news_date():
    news = [f for f in v.parse_research(RESEARCH) if f.section == "Recent news"][0]
    assert news.date == "2026-09-15"
    assert news.claim == "Raised a seed round."


def test_url_keeps_parentheses_inside_url():
    people = [f for f in v.parse_research(RESEARCH) if f.section == "Key people"][0]
    assert people.url == WIKI_URL


def test_pending_and_hypothesis_have_their_own_kind():
    kinds = [f.kind for f in v.parse_research(RESEARCH)]
    assert kinds == ["fact", "fact", "pending", "fact", "fact", "hypothesis"]


def test_star_bullets_and_plain_headings_are_accepted():
    text = (
        "Snapshot\n"
        f"* Hello sold trackers. (source: https://a.com/x) (quote: \"sold trackers\")\n"
        "Recent news\n"
        "* [Pending] no data found\n"
    )
    facts = v.parse_research(text)
    assert [(f.section, f.kind) for f in facts] == [
        ("Snapshot", "fact"), ("Recent news", "pending"),
    ]
    assert facts[0].url == "https://a.com/x"


def test_numbered_and_bold_headings():
    text = "## 1. Snapshot\n- A. (source: https://a.com) (quote: \"a b\")\n**Key people**\n- B. (source: https://b.com) (quote: \"c d\")"
    sections = [f.section for f in v.parse_research(text)]
    assert sections == ["Snapshot", "Key people"]


def test_fact_without_quote_has_none():
    fact = v.parse_research("## Snapshot\n- Claim. (source: https://a.com)")[0]
    assert fact.url == "https://a.com"
    assert fact.quote is None


def test_fact_without_source_has_none_url():
    fact = v.parse_research('## Snapshot\n- Claim. (quote: "some words")')[0]
    assert fact.url is None
    assert fact.quote == "some words"


def test_quote_may_contain_parentheses_and_curly_quotes():
    fact = v.parse_research(
        '## Snapshot\n- Claim. (source: https://a.com) (quote: “He (the CEO) said hi”)'
    )[0]
    assert fact.quote == "He (the CEO) said hi"


def test_searches_performed_line_is_ignored():
    facts = v.parse_research("Searches performed: 0 (queries: none)\n\n## Snapshot\n- [Pending] no data found")
    assert len(facts) == 1 and facts[0].kind == "pending"


def test_empty_text():
    assert v.parse_research("") == []


# -------------------------------------------------------------- comparer
def test_exact_quote_found_despite_footnotes_and_spacing():
    assert v.match_ratio(QUOTE, PAGE) == 1.0


def test_quote_with_footnote_marker_inside_page():
    page = "Hello was an American technology [ 3 ] company that sold sleep tracking devices"
    assert v.match_ratio("technology company that sold sleep tracking devices", page) == 1.0


def test_unrelated_page_scores_low():
    page = "A banana is an elongated edible fruit produced by several kinds of plants."
    assert v.match_ratio(QUOTE, page) < 0.3


def test_paraphrase_scores_below_threshold():
    paraphrase = "Hello made gadgets for tracking how people sleep."
    assert v.match_ratio(paraphrase, PAGE) < v.MATCH_THRESHOLD


def test_non_latin_text_is_compared():
    page = "Компанія була заснована у 2015 році у Львові."
    assert v.match_ratio("заснована у 2015 році", page) == 1.0


def test_empty_quote_or_page_gives_zero():
    assert v.match_ratio("", PAGE) == 0.0
    assert v.match_ratio(QUOTE, "") == 0.0


def test_missing_numbers_reports_absent_numbers():
    assert v.missing_numbers("Founded in 2013 with 40 staff", "founded in 2013") == ["40"]


# ----------------------------------------------------------- verify_fact
def fact(url="https://a.com", quote=QUOTE, claim="Claim"):
    return v.Fact("fact", "Snapshot", claim, url=url, quote=quote)


def test_status_missing_source():
    assert v.verify_fact(fact(url=None), None)["status"] == "missing_source"


def test_status_missing_quote():
    assert v.verify_fact(fact(quote=None), None)["status"] == "missing_quote"


def test_status_unreachable_keeps_reason():
    result = v.verify_fact(fact(), v.FetchResult(False, error="HTTP 403"))
    assert result["status"] == "unreachable"
    assert result["detail"] == "HTTP 403"


@pytest.mark.parametrize("code", [404, 410])
def test_status_dead_link_for_missing_pages(code):
    page = v.FetchResult(False, error=f"HTTP {code}", status_code=code)
    result = v.verify_fact(fact(), page)
    assert result["status"] == "dead_link"
    assert result["detail"] == f"HTTP {code}"


@pytest.mark.parametrize("code", [403, 429, 500])
def test_status_unreachable_for_blocking_and_server_errors(code):
    page = v.FetchResult(False, error=f"HTTP {code}", status_code=code)
    assert v.verify_fact(fact(), page)["status"] == "unreachable"


def test_status_unreachable_when_not_fetched():
    assert v.verify_fact(fact(), None)["status"] == "unreachable"


def test_status_supported_and_final_url():
    page = v.FetchResult(True, WIKI_URL, PAGE)
    result = v.verify_fact(fact(), page)
    assert result["status"] == "supported"
    assert result["final_url"] == WIKI_URL
    assert result["match_ratio"] == 1.0


def test_status_not_found_for_wrong_page():
    page = v.FetchResult(True, "https://en.wikipedia.org/wiki/Banana", "A banana is a fruit.")
    assert v.verify_fact(fact(), page)["status"] == "not_found"


# --------------------------------------------------------------- fetcher
def make_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_html_to_text_strips_tags_and_scripts():
    html = "<html><script>var x=1;</script><body><p>Hello <b>world</b></p></body></html>"
    assert v.html_to_text(html) == "Hello world"


def test_fetch_follows_redirect_and_returns_text():
    def handler(request):
        if request.url.host == "redirect.example":
            return httpx.Response(302, headers={"location": "https://real.example/page"})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<p>Real <i>page</i> text</p>")

    async def run():
        async with make_client(handler) as client:
            return await v.fetch_page_text("https://redirect.example/x", client)

    result = asyncio.run(run())
    assert result.ok and result.final_url == "https://real.example/page"
    assert result.text == "Real page text"


def test_fetch_403_is_not_ok():
    async def run():
        async with make_client(lambda r: httpx.Response(403)) as client:
            return await v.fetch_page_text("https://blocked.example", client)

    result = asyncio.run(run())
    assert not result.ok and result.error == "HTTP 403" and result.status_code == 403


def test_fetch_404_keeps_status_code():
    async def run():
        async with make_client(lambda r: httpx.Response(404)) as client:
            return await v.fetch_page_text("https://plausible.io/enterprise", client)

    result = asyncio.run(run())
    assert not result.ok and result.status_code == 404


def test_fetch_rejects_non_text_content():
    handler = lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    async def run():
        async with make_client(handler) as client:
            return await v.fetch_page_text("https://x.example/a.pdf", client)

    assert "unsupported" in asyncio.run(run()).error


def test_fetch_network_error_is_not_ok():
    def handler(request):
        raise httpx.ConnectError("boom")

    async def run():
        async with make_client(handler) as client:
            return await v.fetch_page_text("https://down.example", client)

    result = asyncio.run(run())
    assert not result.ok and "ConnectError" in result.error


def test_disk_cache_avoids_second_download(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>cached text</p>")

    async def run():
        async with make_client(handler) as client:
            first = await v.fetch_with_cache("https://c.example", client, tmp_path)
            second = await v.fetch_with_cache("https://c.example", client, tmp_path)
            return first, second

    first, second = asyncio.run(run())
    assert first.text == second.text == "cached text"
    assert len(calls) == 1


def test_failed_fetch_is_not_cached(tmp_path):
    async def run():
        async with make_client(lambda r: httpx.Response(500)) as client:
            await v.fetch_with_cache("https://c.example", client, tmp_path)

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


# ----------------------------------------------------------- orchestrator
def fake_fetch(pages):
    calls = []

    async def fetch(url):
        calls.append(url)
        return pages.get(url, v.FetchResult(False, error="HTTP 404", status_code=404))

    fetch.calls = calls
    return fetch


def test_verify_research_end_to_end():
    fetch = fake_fetch({
        GOOGLE_URL: v.FetchResult(True, WIKI_URL, PAGE),
        WIKI_URL: v.FetchResult(True, WIKI_URL, PAGE),
        "https://news.example.com/seed": v.FetchResult(True, "https://news.example.com/seed", "Unrelated text."),
        # https://example.com/a is missing -> HTTP 404 -> unreachable
    })
    result = asyncio.run(v.verify_research(RESEARCH, fetch=fetch))
    assert result["status"] == "ok"
    statuses = [f["status"] for f in result["facts"]]
    assert statuses == ["supported", "not_found", "supported", "dead_link"]
    assert result["counts"]["pending"] == 1
    assert result["counts"]["hypothesis"] == 1


def test_each_url_is_fetched_once():
    text = (
        '## Snapshot\n'
        '- A. (source: https://a.com) (quote: "alpha beta")\n'
        '- B. (source: https://a.com) (quote: "gamma delta")\n'
    )
    fetch = fake_fetch({"https://a.com": v.FetchResult(True, "https://a.com", "alpha beta gamma delta")})
    result = asyncio.run(v.verify_research(text, fetch=fetch))
    assert fetch.calls == ["https://a.com"]
    assert [f["status"] for f in result["facts"]] == ["supported", "supported"]


def test_facts_without_source_or_quote_do_not_trigger_fetch():
    text = '## Snapshot\n- A. (quote: "alpha")\n- B. (source: https://a.com)\n'
    fetch = fake_fetch({})
    result = asyncio.run(v.verify_research(text, fetch=fetch))
    assert fetch.calls == []
    assert [f["status"] for f in result["facts"]] == ["missing_source", "missing_quote"]


def test_all_pending_research_is_ok_not_parse_error():
    text = "Searches performed: 3 (queries: x)\n\n## Snapshot\n- [Pending] no data found\n"
    result = asyncio.run(v.verify_research(text, fetch=fake_fetch({})))
    assert result["status"] == "ok" and result["facts"] == []


def test_unparseable_research_is_parse_error():
    result = asyncio.run(v.verify_research("Some prose without any bullets.", fetch=fake_fetch({})))
    assert result["status"] == "parse_error"


def test_empty_research():
    assert asyncio.run(v.verify_research("  ", fetch=fake_fetch({})))["status"] == "empty"


# ---------------------------------------------------------------- report
def test_format_lists_only_problem_facts():
    fetch = fake_fetch({GOOGLE_URL: v.FetchResult(True, WIKI_URL, PAGE)})
    result = asyncio.run(v.verify_research(RESEARCH, fetch=fetch))
    report = v.format_verification(result)
    assert report.startswith("SOURCE VERIFICATION")
    assert "supported=1" in report
    assert "Hello sold sleep trackers." not in report      # supported facts are not listed
    assert "[dead_link]" in report
    assert "HTTP 404" in report                            # the reason is shown


def test_format_parse_error_and_empty():
    assert "PARSE ERROR" in v.format_verification({"status": "parse_error", "counts": {}, "facts": []})
    assert "empty" in v.format_verification({"status": "empty", "counts": {}, "facts": []})


# ------------------------------------------------- weak_support and excerpts
LONG_PAGE = (
    "Intro text about cookies and privacy. " * 20
    + "Plausible is an open source web analytics tool that was founded in 2018 "
    "by Uku Taht and Marko Saric. "
    + "Footer text about pricing and plans. " * 20
)


def ok_page(text):
    return v.FetchResult(True, "https://a.com", text, status_code=200)


def test_claim_coverage_counts_key_words_only():
    assert v.claim_coverage("The tool is open source.", "open source tool") == 1.0
    assert v.claim_coverage("Headquartered in Tallinn", "incorporated in Estonia") < 0.5
    assert v.claim_coverage("a is of", "anything") == 1.0       # no key words


def test_best_fragment_returns_offsets_in_cleaned_page():
    size, span = v.best_fragment("founded in 2018 by Uku Taht", LONG_PAGE)
    assert size == 6
    assert LONG_PAGE[span[0]:span[1]].lower() == "founded in 2018 by uku taht"


def test_best_fragment_nothing_in_common():
    assert v.best_fragment("zzz qqq", "hello world") == (0, None)
    assert v.best_fragment("", "hello") == (0, None)


def test_clean_supported_fact_has_no_flag_and_no_excerpt():
    f = v.Fact("fact", "Snapshot", "Plausible was founded in 2018 by Uku Taht.",
               "https://a.com", "founded in 2018 by Uku Taht")
    r = v.verify_fact(f, ok_page(LONG_PAGE))
    assert r["status"] == "supported"
    assert r["weak_support"] is False
    assert r["excerpt"] is None


def test_weak_support_when_quote_does_not_cover_claim():
    f = v.Fact("fact", "Snapshot", "Plausible is headquartered in Tallinn, Estonia.",
               "https://a.com", "open source web analytics tool")
    r = v.verify_fact(f, ok_page(LONG_PAGE))
    assert r["status"] == "supported"             # the quote itself is on the page
    assert r["weak_support"] is True
    assert "key words" in r["detail"]
    assert "open source web analytics tool" in r["excerpt"]


def test_weak_support_when_claim_number_is_not_on_page():
    f = v.Fact("fact", "Snapshot", "Plausible was founded in 2019.",
               "https://a.com", "was founded in 2018")
    r = v.verify_fact(f, ok_page(LONG_PAGE))
    assert r["weak_support"] is True
    assert r["missing_numbers"] == ["2019"]
    assert "2019" in r["detail"]


def test_excerpt_is_capped_and_marks_truncation():
    page = "word " * 5000
    f = v.Fact("fact", "S", "Totally different claim here.", "https://a.com",
               " ".join(["word"] * 300))
    r = v.verify_fact(f, ok_page(page))
    assert r["weak_support"] is True
    assert len(r["excerpt"]) <= v.MAX_EXCERPT_CHARS + 6
    assert r["excerpt"].endswith("...")


def test_not_found_gives_closest_fragment_and_page_length():
    f = v.Fact("fact", "Snapshot", "Claim", "https://a.com",
               "Plausible was founded in 2012 by Elon Musk and friends")
    r = v.verify_fact(f, ok_page(LONG_PAGE))
    assert r["status"] == "not_found"
    assert f"{len(LONG_PAGE)} chars" in r["detail"]
    assert "founded in" in r["excerpt"]


def test_not_found_without_overlap_has_no_excerpt():
    f = v.Fact("fact", "S", "Claim", "https://a.com", "zebra giraffe lion elephant")
    r = v.verify_fact(f, ok_page(LONG_PAGE))
    assert r["status"] == "not_found"
    assert r["excerpt"] is None
    assert "no overlapping text" in r["detail"]


def test_dead_link_unreachable_and_missing_have_no_excerpt():
    for page in (v.FetchResult(False, error="HTTP 404", status_code=404),
                 v.FetchResult(False, error="HTTP 403", status_code=403)):
        assert v.verify_fact(fact(), page)["excerpt"] is None
    assert v.verify_fact(fact(url=None), None)["excerpt"] is None
    assert v.verify_fact(fact(quote=None), None)["excerpt"] is None


def result_with(*facts, counts=None):
    return {"status": "ok", "counts": counts or {}, "facts": list(facts)}


def verified(f, page):
    return v.verify_fact(f, page)


def test_format_shows_excerpt_for_weak_support_and_not_found_only():
    weak = verified(v.Fact("fact", "S", "Plausible is headquartered in Tallinn.",
                           "https://a.com/w", "open source web analytics tool"),
                    ok_page(LONG_PAGE))
    nf = verified(v.Fact("fact", "S", "Founded by Elon.", "https://a.com/n",
                         "Plausible was founded in 2012 by Elon Musk and friends"),
                  ok_page(LONG_PAGE))
    dead = verified(fact(url="https://a.com/d"), v.FetchResult(False, error="HTTP 404",
                                                              status_code=404))
    report = v.format_verification(result_with(weak, nf, dead))
    assert "[weak_support] Plausible is headquartered in Tallinn." in report
    assert "[not_found] Founded by Elon." in report
    assert "[dead_link]" in report
    assert report.count("page text:") == 2             # none for the dead link


def test_format_missing_source_shows_no_url_not_none():
    report = v.format_verification(result_with(verified(fact(url=None), None)))
    assert "(no URL)" in report
    assert "None" not in report


def test_format_caps_number_of_excerpts_and_prefers_not_found():
    weak = [verified(v.Fact("fact", "S", f"Different claim number {i}.", "https://a.com",
                            "open source web analytics tool"), ok_page(LONG_PAGE))
            for i in range(v.MAX_EXCERPTS)]
    nf = verified(v.Fact("fact", "S", "Founded by Elon.", "https://a.com",
                         "Plausible was founded in 2012 by Elon Musk and friends"),
                  ok_page(LONG_PAGE))
    report = v.format_verification(result_with(*weak, nf))     # not_found comes last
    assert report.count("page text:") == v.MAX_EXCERPTS
    nf_index = report.index("[not_found]")
    assert report.index("page text:", nf_index) > nf_index     # not_found kept its excerpt
    assert "[weak_support]" in report                          # capped ones are still listed


def test_counts_include_weak_support_only_when_present():
    pages = {"https://a.com": ok_page(LONG_PAGE)}
    clean = "- Plausible was founded in 2018 by Uku Taht. (source: https://a.com) (quote: \"founded in 2018 by Uku Taht\")"
    weak = "- Totally different words here. (source: https://a.com) (quote: \"open source web analytics tool\")"

    async def run(text):
        async def fetch(url):
            return pages[url]
        return await v.verify_research("## Snapshot\n" + text, fetch=fetch)

    assert "weak_support" not in asyncio.run(run(clean))["counts"]
    assert asyncio.run(run(weak))["counts"]["weak_support"] == 1


def test_parse_error_shows_start_of_research():
    result = asyncio.run(v.verify_research("Just some prose without bullets.\nAnother line."))
    assert result["status"] == "parse_error"
    report = v.format_verification(result)
    assert "PARSE ERROR" in report
    assert "Just some prose without bullets." in report


# ------------------------------------------------- number spellings
@pytest.mark.parametrize("claim,page", [
    ("Over 30,000 websites.", "from more than 30k websites"),
    ("Over 30k websites.", "from more than 30,000 websites"),
    ("Revenue grew to 1,250 customers.", "1250 customers"),
])
def test_number_spellings_are_equal(claim, page):
    assert v.missing_numbers(claim, page) == []


def test_really_different_numbers_are_still_missing():
    assert v.missing_numbers("Over 30,000 websites.", "from more than 28k websites") == ["30000"]


# ------------------------------------------------- date verification
@pytest.mark.parametrize("page", [
    "Published 2026-10-26 by the team",
    "Published October 26, 2026 by the team",
    "Published Oct 26 2026",
    "Published Oct. 26th, 2026",
    "Published 26 October 2026",
    "Published 26th of October, 2026",
    "Опубліковано 26.10.2026",
    "<time> 2026/10/26 </time>",
    "[page dates: 2026-10-26T12:00:00Z]",
])
def test_full_date_is_found_in_common_formats(page):
    assert v.check_date_on_page("2026-10-26", page) == v.DATE_EXACT


@pytest.mark.parametrize("page", [
    "Last updated: September 2026",
    "Updated Sept. 2026",
    "Posted 2026-09",
])
def test_month_only_is_imprecise(page):
    assert v.check_date_on_page("2026-09-15", page) == v.DATE_MONTH


@pytest.mark.parametrize("page", [
    "Published October 27, 2026",          # other day
    "Published October 2025",             # other year
    "Version 2026-10-261 released",       # digits glued to the date
    "No dates here at all",
    "",
])
def test_other_dates_do_not_count(page):
    assert v.check_date_on_page("2026-10-26", page) == v.DATE_MISSING


def test_invalid_date_string_returns_none():
    assert v.check_date_on_page("2026-13-45", "anything") is None
    assert v.check_date_on_page("soon", "anything") is None


def test_day_is_not_confused_with_other_numbers():
    # day 5 must not match inside "15"
    assert v.check_date_on_page("2026-10-05", "Published October 15, 2026") == v.DATE_MISSING


def dated_fact(date):
    return v.Fact("fact", "Recent news", "Something happened.", "https://a.com",
                  "something happened", date=date)


def test_fact_without_date_has_no_date_check():
    r = v.verify_fact(dated_fact(None), ok_page("Something happened on a day."))
    assert r["date_check"] is None


def test_verify_fact_records_date_check():
    page = ok_page("Something happened. Published October 26, 2026.")
    assert v.verify_fact(dated_fact("2026-10-26"), page)["date_check"] == v.DATE_EXACT
    assert v.verify_fact(dated_fact("2026-10-28"), page)["date_check"] == v.DATE_MISSING


def test_date_is_not_checked_when_page_was_not_fetched():
    r = v.verify_fact(dated_fact("2026-10-26"), v.FetchResult(False, error="HTTP 403",
                                                             status_code=403))
    assert r["date_check"] is None


def test_html_to_text_appends_hidden_publication_dates():
    html = (
        '<html><head>'
        '<meta property="article:published_time" content="2026-10-26T10:00:00Z">'
        '<meta name="viewport" content="width=device-width">'
        '<script type="application/ld+json">{"datePublished": "2026-10-24"}</script>'
        '</head><body><time datetime="2026-10-25">yesterday</time><p>Hello</p>'
        '<script>var x = 1;</script></body></html>'
    )
    text = v.html_to_text(html)
    assert "Hello" in text and "var x" not in text
    assert "2026-10-26T10:00:00Z" in text
    assert "2026-10-24" in text and "2026-10-25" in text
    assert "width=device-width" not in text
    assert v.check_date_on_page("2026-10-24", text) == v.DATE_EXACT


def test_html_without_dates_gets_no_marker():
    assert "page dates" not in v.html_to_text("<p>Hello</p>")


def test_report_lists_unverified_date_and_counts_imprecise():
    news = "## Recent news\n"
    research = (
        news
        + "- Hello world. (date: 2026-10-28) (source: https://a.com/1) (quote: \"hello world\")\n"
        + "- Hello world. (date: 2026-09-15) (source: https://a.com/2) (quote: \"hello world\")\n"
        + "- Hello world. (date: 2026-10-26) (source: https://a.com/3) (quote: \"hello world\")\n"
    )
    pages = {
        "https://a.com/1": ok_page("hello world. Published October 26, 2026."),
        "https://a.com/2": ok_page("hello world. Last updated: September 2026"),
        "https://a.com/3": ok_page("hello world. Published October 26, 2026."),
    }

    async def fetch(url):
        return pages[url]

    result = asyncio.run(v.verify_research(research, fetch=fetch))
    assert result["counts"]["date_unverified"] == 1
    assert result["counts"]["date_imprecise"] == 1
    report = v.format_verification(result)
    assert "[date_unverified] Hello world. (https://a.com/1)" in report
    assert "2026-10-28 does not appear on the page" in report
    assert "https://a.com/2" not in report        # imprecise dates are only counted
    assert "https://a.com/3" not in report


def test_clean_research_has_no_date_counts():
    research = ("## Recent news\n- Ok. (date: 2026-10-26) (source: https://a.com/1) "
                "(quote: \"hello world\")\n")

    async def fetch(url):
        return ok_page("hello world. Published 2026-10-26.")

    result = asyncio.run(v.verify_research(research, fetch=fetch))
    assert "date_unverified" not in result["counts"]
    assert "date_imprecise" not in result["counts"]


def test_cache_key_is_versioned(tmp_path):
    import hashlib
    old_name = hashlib.sha256(b"https://a.com").hexdigest() + ".json"
    assert v._cache_file(tmp_path, "https://a.com").name != old_name