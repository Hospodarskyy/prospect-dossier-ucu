# Component evaluation

Generated 2026-11-16 11:35 UTC by `python -m eval.eval_components` from 6 collected runs (eval/runs/) and the labelled sets in eval/data/.

## init_state: request parsing

Turns the JSON request into company, domain (normalized) and context; rejects bad input before any model call.

| metric | value |
|---|---|
| cases | 16 |
| accuracy | 1 |
| valid requests parsed correctly | 1 |
| invalid requests rejected with the right error | 1 |

| case | expected | ok | got |
|---|---|---|---|
| valid request | parsed | yes | {"company": "Plausible Analytics", "domain": "plausible.io", "context": ""} |
| URL instead of a domain | parsed | yes | {"company": "Plausible Analytics", "domain": "plausible.io", "context": ""} |
| upper case and trailing dot | parsed | yes | {"company": "PostHog", "domain": "posthog.com", "context": ""} |
| port | parsed | yes | {"company": "Supabase", "domain": "supabase.com", "context": ""} |
| context given | parsed | yes | {"company": "Doctolib", "domain": "doctolib.com", "context": "They may need a support assistant"} |
| unknown keys are ignored | parsed | yes | {"company": "Rozetka", "domain": "rozetka.com.ua", "context": ""} |
| spaces around the company | parsed | yes | {"company": "Rozetka", "domain": "rozetka.com.ua", "context": ""} |
| internationalized domain | parsed | yes | {"company": "Rozetka", "domain": "xn--80ajfnrlr.xn--j1amh", "context": ""} |
| missing domain | error | yes | domain is required |
| empty company | error | yes | company is required and must be a non-empty string |
| not JSON | error | yes | request must be a JSON object like {"company": "...", "domain": "..."} |
| JSON list | error | yes | request must be a JSON object, not list |
| domain without a dot | error | yes | domain must have at least one dot: 'localhost' |
| IP address | error | yes | IP addresses are not accepted as a domain: '192.168.0.1' |
| user info in the domain | error | yes | domain must not contain user info: 'admin@plausible.io' |
| context is not a string | error | yes | context must be a string |

- Deterministic code: this is a labelled test set more than a quality measure; it shows the input contract the rest of the pipeline relies on.

## researcher

Searches the web (Google Search grounding) and writes facts with a URL and a verbatim quote, or [Pending].

| metric | value |
|---|---|
| real-company runs | 5 |
| grounded rate, 1st iteration (supported / checkable) | 0.885 |
| grounded rate, final iteration | 1 |
| weak support (share of supported facts) | 0.494 |
| misquote rate (quote not on the page) | 0 |
| dead-link rate | 0 |
| unreachable pages (excluded above) | 0.024 |
| section coverage (mean share of the 5 fact sections with a supported fact) | 0.96 |
| runs with at least one supported recent news item | 0.8 |
| dated news within 90 days | 1 |
| news dates found on the page | 1 |
| fictional company: facts with a source (target 0) | 0 |

| run | iterations | facts (final) | grounded 1st | grounded final | weak share | misquoted | dead links | unreachable | sections covered | pending items | news (fresh/dated) | searches reported |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| plausible-repeat | 1 | 19 | 1 | 1 | 0.316 | 0 | 0 | 0 | 4/5 | 1 | 0/0 | 5 |
| posthog | 2 | 16 | 0.875 | 1 | 0.562 | 0 | 0 | 0 | 5/5 | 0 | 3/3 | 31 |
| supabase | 2 | 20 | 0.714 | 1 | 0.5 | 0 | 0 | 0 | 5/5 | 0 | 4/4 | 25 |
| rozetka | 1 | 13 | 1 | 1 | 0.846 | 0 | 0 | 0 | 5/5 | 0 | 3/3 | 9 |
| doctolib | 2 | 15 | 0.889 | 1 | 0.308 | 0 | 0 | 2 | 5/5 | 0 | 1/1 | 15 |
| zorblax | 1 | 0 | — | — | — | 0 | 0 | 0 | 0/5 | 5 | 0/0 | 5 |

- Grounded = SourceVerifier found the quote on the cited page; it does not prove the claim says no more than the quote (that is the weak-support flag and the judge).
- 1st vs final iteration shows what the judge loop adds.

## SourceVerifier

Fetches every cited page and checks that the quote is on it (and the date); flags claims that say more than the quote.

| metric | value |
|---|---|
| cases (synthetic + hand-labelled) | 151 + 12 |
| 'supported' precision | 1 |
| 'supported' recall | 1 |
| 'supported' F1 | 1 |
| weak-support flag precision (synthetic) | 1 |
| weak-support flag recall (synthetic) | 0.543 |
| weak-support flag F1 (synthetic) | 0.704 |
| date check accuracy | 1 |
| real facts: fully correct | 0.667 |
| real facts: weak-support flag precision | 0.4 |
| real facts: weak-support flag recall | 0.667 |

| variant | cases | correct | accuracy | expected | typical result |
|---|---|---|---|---|---|
| exact | 20 | 20 | 1 | supported | supported ×20 |
| format_noise | 20 | 20 | 1 | supported | supported ×20 |
| word_swap | 20 | 20 | 1 | not_found | not_found ×20 |
| other_page | 19 | 19 | 1 | not_found | not_found ×19 |
| overstated_strong | 20 | 20 | 1 | supported + weak | supported + weak ×20 |
| overstated_subtle | 20 | 0 | 0 | supported + weak | supported ×20 |
| number_changed | 6 | 5 | 0.833 | supported + weak | supported + weak ×5, supported ×1 |
| date_not_on_page | 20 | 20 | 1 | supported | supported / date missing ×20 |
| date_on_page | 6 | 6 | 1 | supported | supported / date exact ×6 |
| manual (real fact) | 12 | 8 | 0.667 | supported | supported + weak ×5, supported ×4, not_found ×3 |

- Positive class of 'supported': the quote really is on the page. Weak-support flag: the claim says more than the quote (counted on cases the verifier marked supported).
- hand-labelled miss: manual-posthog-0: expected supported, got supported + weak (quote contains only 45% of the claim's key words)
- hand-labelled miss: manual-supabase-1: expected supported, got supported + weak (quote contains only 50% of the claim's key words)
- hand-labelled miss: manual-posthog-4: expected supported, got supported + weak (quote contains only 31% of the claim's key words)
- hand-labelled miss: manual-supabase-6: expected supported + weak, got supported ()

## judge

Reads the research and the verification report and returns pass or fail with the problems found.

| metric | value |
|---|---|
| result file | judge_20261113_123525.json |
| model / thinking | gemini-3.8-flash / low |
| cases | 13 |
| accuracy | 1 |
| precision of 'fail' (bad research caught, not good research rejected) | 1 |
| recall of 'fail' (share of bad research caught) | 1 |
| accuracy, benign mutations (3) | 1 |
| accuracy, semantic mutations (5) | 1 |
| accuracy, structural mutations (5) | 1 |

| mutation | group | expected | got | ok | judge summary |
|---|---|---|---|---|---|
| baseline | benign | pass | pass | yes | All sections are thoroughly covered with valid sources and direct quotes, and news items fall within the 90-day window. Weak support hints are fully verified by |
| reverse_bullets | benign | pass | pass | yes | All sections are thoroughly covered with valid sources, quotes, and recent news within the required timeframe. |
| all_pending | benign | pass | pass | yes | All sections are properly marked with honest [Pending] entries following 14 documented searches. The notes adhere to the coverage and formatting guidelines. |
| strip_all_urls | structural | fail | fail | yes | Every single bullet is missing a source URL. Please reformat all facts to include source URLs alongside the quotes, or mark missing sections as [Pending] if sou |
| strip_one_url | structural | fail | fail | yes | The first bullet under Snapshot is missing a source URL. Please provide a valid source URL for 'Plausible Analytics is an independent open-source web analytics  |
| stale_news | structural | fail | fail | yes | The dates for both news items were unverified on their source pages (which state October 2026 rather than 2025-09-24). Please copy the exact dates shown on the  |
| empty_section | structural | fail | fail | yes | The 'Recent news' section is completely empty without any facts or an honest '- [Pending] no data found' marker. Please provide sourced news items published wit |
| drop_section | structural | fail | fail | yes | The 'Recent news' section is completely missing. Please add sourced recent news within the last 90 days or explicitly mark the section with '- [Pending] no data |
| fake_date | semantic | fail | fail | yes | Both items in Recent news failed verification because the date 2026-10-09 does not appear on the source pages (the article states October 26, 2026). Please upda |
| swap_all_urls | semantic | fail | fail | yes | All cited URLs point to completely unrelated Wikipedia articles (Banana, Roman Empire, Photosynthesis) and fail verification, leaving all claims unsourced. Plea |
| swap_one_url | semantic | fail | fail | yes | The first Snapshot bullet cites the Wikipedia article for 'Banana' where the quote was not found. Please provide a valid source URL and matching quote for this  |
| overstate_claims | semantic | fail | fail | yes | Snapshot contains unsupported claims regarding being the market leader with over 1 million paying customers, and revenue growing tenfold in 2025; please remove  |
| overstate_one_subtle | semantic | fail | fail | yes | Narrow the claim that Plausible is 'the most popular analytics tool in Europe', as neither the cited quote nor the underlying page supports this statement. |

- Positive class: 'fail' (the research must go back). Benign mutations must pass, structural and semantic ones must fail.

## writer

Writes the dossier from the verified research; picks case studies with load_seller_cases and checks itself with check_dossier_format.

| metric | value |
|---|---|
| runs with a dossier | 6 |
| format valid | 1 |
| format valid at the first check_dossier_format call | 1 |
| within 900 words | 1 |
| URLs that come from the research or the case list | 1 |
| faithful fact bullets (match a supported research fact) | 0.976 |
| bullets citing an unverified source | 0.024 |
| hypotheses based on a supported fact | 1 |
| sections honest about missing data (content ⇔ supported research) | 1 |
| sections with facts but no supported research | 0 |
| sections left [Pending] although the research had facts | 0 |
| cited case studies: precision (relevant / cited) | 0.6 |
| cited case studies: recall (cited / relevant) | 0.333 |
| cited case studies all returned by load_seller_cases | 1 |
| no case cited when none fits (fictional company) | 1 |

| run | format ok | words | URLs from research/cases | faithful bullets | other bullets | sections dropped / unsupported | cases cited (relevant) | format checks (1st ok) |
|---|---|---|---|---|---|---|---|---|
| plausible-repeat | yes | 581 | 25/25 | 19/19 | hypothesis grounded 4 | — | cs-03, cs-01 (cs-01, cs-03) | 1 (True) |
| posthog | yes | 552 | 19/19 | 15/15 | hypothesis grounded 3 | — | cs-01 (cs-01, cs-02) | 1 (True) |
| supabase | yes | 606 | 24/24 | 20/20 | hypothesis grounded 3 | — | cs-01 (cs-02, cs-03) | 1 (True) |
| rozetka | yes | 651 | 17/17 | 13/13 | hypothesis grounded 4 | — |  (cs-04, cs-05) | 1 (True) |
| doctolib | yes | 561 | 19/19 | 13/15 | unverified source 2, hypothesis grounded 3 | — | cs-02 (cs-06) | 1 (True) |
| zorblax | yes | 140 | 0/0 | 0/0 |  | — |  (none fits) | 1 (True) |

- A fact bullet is faithful when at least 50% of its key words are in a supported research fact with the same URL; 'rewritten' means the URL is right but the wording moved away from the verified claim.
- '!' marks a section that has facts in the dossier but none supported in the final research.

## load_seller_cases

Returns up to 5 of the seller's case studies that best match the industry and technologies the writer passes.

| metric | value |
|---|---|
| profiles: inputs | 10 |
| profiles: hit@1 | 1 |
| profiles: MRR | 1 |
| eval runs: inputs | 5 |
| eval runs: hit@1 | 1 |
| eval runs: MRR | 1 |

| input | source | industry | tech | relevant | ranking | rank |
|---|---|---|---|---|---|---|
| analytics SaaS, ClickHouse | profile | SaaS | ClickHouse, event ingestion | cs-01 | cs-01 cs-02 cs-03 cs-04 cs-05 | 1 |
| SaaS, slow reporting on PostgreSQL | profile | SaaS | PostgreSQL, reporting queries | cs-02 | cs-02 cs-01 cs-03 cs-04 cs-05 | 1 |
| self-hosted SaaS on Hetzner | profile | SaaS | Docker, Hetzner, self-hosted | cs-03 | cs-03 cs-01 cs-02 cs-04 cs-05 | 1 |
| online store, chargebacks | profile | E-commerce | chargebacks, card payments | cs-04 | cs-04 cs-05 cs-01 cs-02 cs-03 | 1 |
| online store, checkout scripts | profile | E-commerce | checkout, third-party scripts | cs-05 | cs-05 cs-04 cs-01 cs-02 cs-03 | 1 |
| HealthTech, support load | profile | HealthTech | support, LLM | cs-06 | cs-06 cs-01 cs-02 cs-03 cs-04 | 1 |
| analytics, Kafka and Kubernetes | profile | Analytics | Kafka, Kubernetes | cs-01 | cs-01 cs-02 cs-03 cs-04 cs-05 | 1 |
| retail, fraud | profile | Retail | fraud, payments | cs-04 | cs-04 cs-05 cs-01 cs-02 cs-03 | 1 |
| SaaS, dbt and BigQuery | profile | SaaS | dbt, BigQuery | cs-02 | cs-02 cs-01 cs-03 cs-04 cs-05 | 1 |
| healthcare, patient chatbot | profile | Healthcare | patient support chatbot | cs-06 | cs-06 cs-01 cs-02 cs-03 cs-04 | 1 |
| plausible-repeat | eval run | SaaS | ClickHouse, PostgreSQL, Elixir, Docker, Hetzner, vertical scaling | cs-01, cs-03 | cs-03 cs-01 cs-02 cs-04 cs-05 | 1 |
| posthog | eval run | SaaS | ClickHouse, PostgreSQL, data pipeline scaling, Django | cs-01, cs-02 | cs-01 cs-02 cs-03 cs-04 cs-05 | 1 |
| supabase | eval run | SaaS | PostgreSQL, database scaling, high availability, provisioning | cs-02, cs-03 | cs-02 cs-01 cs-03 cs-04 cs-05 | 1 |
| rozetka | eval run | E-commerce | PHP, microservices, warehouse automation, logistics, PostgreSQL, RabbitMQ | cs-04, cs-05 | cs-04 cs-05 cs-02 cs-01 cs-03 | 1 |
| doctolib | eval run | Healthcare | Ruby on Rails, PostgreSQL, Aurora, scaling, security, AI | cs-06 | cs-06 cs-02 cs-01 cs-03 cs-04 | 1 |

- Scoring is keyword-based: +2 for the same industry, +1 per technology or problem word that matches. Synonyms (Retail vs E-commerce, Healthcare vs HealthTech) are not understood.

## memory / What changed

Loads the previous dossier of the domain, lets the writer compare, and saves the new facts as memory.

| metric | value |
|---|---|
| first requests: What changed correctly [Pending] | 1 |
| repeated requests: previous dossier loaded and changes reported | 1 |
| finished runs that saved their memory | 1 |

| run | repeat | previous dossier | What changed | well formed | ok | memory saved |
|---|---|---|---|---|---|---|
| plausible-repeat | yes | 2026-11-12 | No material changes since 2026-11-12. | yes | yes | yes |
| posthog | no | none | [Pending] | yes | yes | yes |
| supabase | no | none | [Pending] | yes | yes | yes |
| rozetka | no | none | [Pending] | yes | yes | yes |
| doctolib | no | none | [Pending] | yes | yes | yes |
| zorblax | no | none | [Pending] | yes | yes | yes |

- Only one repeated request is in the set (Plausible, memory from 2026-11-12); whether the listed changes are true is checked by the judge loop, not here.

## whole pipeline

One request end to end: research loop, writer, finalize; hard stops on calls, cost and time.

| metric | value |
|---|---|
| runs | 6 |
| status ok | 0.833 |
| status partial | 0.167 |
| status failed | 0 |
| judge passed at the 1st iteration | 0.5 |
| mean research iterations | 1.5 |
| mean cost $ | 0.131 |
| max cost $ | 0.209 |
| runs within $0.40 | 1 |
| mean time s | 200.683 |
| max time s | 311.1 |
| runs within 540 s | 1 |
| runs stopped by a limit | 1 |

| run | status | iterations | judge | model calls | searches | cost $ | time s | stop |
|---|---|---|---|---|---|---|---|---|
| plausible-repeat | ok | 1 | pass | 5 | 4 | 0.109 | 162.5 |  |
| posthog | partial | 2 | fail → fail | 7 | 21 | 0.148 | 230.3 | searches |
| supabase | ok | 2 | fail → pass | 8 | 8 | 0.209 | 311.1 |  |
| rozetka | ok | 1 | pass | 6 | 4 | 0.124 | 178 |  |
| doctolib | ok | 2 | fail → pass | 7 | 11 | 0.175 | 288.5 |  |
| zorblax | ok | 1 | pass | 5 | 5 | 0.021 | 33.7 |  |
