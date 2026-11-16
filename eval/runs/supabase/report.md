# Supabase

## Snapshot
- Supabase provides an open-source backend platform designed to help developers build and manage applications (https://pitchbook.com/profiles/company/437773-51)
- Supabase operates as a 100% distributed organization without physical offices across 37 countries (https://supabase.com/blog/supabase-series-e)
- Supabase has over 350 team members across more than 60 countries (https://supabase.com/careers)
- Supabase secured $150 million in new funding led by investment firm GIC (https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html)

## Recent news
- Supabase raised $150 million in new funding led by GIC (date: 2026-10-02) (https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html)
- Supabase acquired Turso to support higher database volumes for agent-driven workloads (date: 2026-10-02) (https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html)
- Supabase released agentic diagnostic tools enabling coding agents to investigate production problems and test fixes (date: 2026-10-02) (https://supabase.com/blog/select-2026-operate-with-confidence)
- Supabase launched a prebuilt connector integration within Google Cloud Gemini Enterprise (date: 2026-09-09) (https://supabase.com/blog/supabase-is-now-available-in-gemini-enterprise)

## Tech signals
- Supabase has 77 open positions advertised on its career portal (https://supabase.com/careers)
- Open engineering positions at Supabase include Platform Engineer for Managed Postgres and Postgres Deployment Engineer (https://supabase.com/careers)
- Supabase's tech stack runs on open-source technologies including Postgres, PostgREST, pgvector, and Deno (https://supabase.com/blog/introducing-osscar-index)
- Supabase's engineering blog publishes deep-dive technical articles on internal tooling and product development (https://supabase.com/blog/categories/engineering)

## Key people
- Paul Copplestone, Co-founder and CEO (https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html)
- Ant Wilson, CTO and Co-Founder (https://supabase.com/blog/authors/ant_wilson)
- Joe Sciarrino, Head of Product (https://supabase.com/blog/authors/joe_sciarrino)
- Sugu Sougoumarane, Head of Multigres (https://supabase.com/blog/authors/sugu_sougoumarane)
- Glauber Costa, Head of Agentic Services (https://www.trendingtopics.eu/supabase-150-million-turso/)

## Likely pains
- Supabase is experiencing rapid expansion, adding over 4 million databases a month with 70% provisioned by AI agents (https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html)
- Security auditors report widespread configuration pitfalls in user deployments such as exposed service keys in client bundles (https://www.ddmarketer.com/gap/every-supabase-audit-finds-the-same-dozen-landmines-b0730f8a)
- Running and scaling PostgreSQL clusters at massive production scale presents operational complexity and high-availability challenges (https://svpost.com/articles/supabase-500m-series-f/)
- Hypothesis: The sudden flood of agent-generated databases places heavy strain on backend database provisioning infrastructure and compute capacity (based on: Supabase is experiencing rapid expansion, adding over 4 million databases a month with 70% provisioned by AI agents) (https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html)
- Hypothesis: Widespread developer misconfigurations of API keys risk public data exposure and create customer support burdens (based on: Security auditors report widespread configuration pitfalls in user deployments such as exposed service keys in client bundles) (https://www.ddmarketer.com/gap/every-supabase-audit-finds-the-same-dozen-landmines-b0730f8a)
- Hypothesis: Managing custom horizontal clustering and distributed replication for Postgres creates substantial ongoing maintenance and operational engineering overhead (based on: Running and scaling PostgreSQL clusters at massive production scale presents operational complexity and high-availability challenges) (https://svpost.com/articles/supabase-500m-series-f/)

## Metacortex angle
- Metacortex can provide specialized systems engineering capacity to support Supabase's platform engineering team in optimizing automated provisioning pipelines and connection pooling under heavy load, addressing the hypothesis that the sudden flood of agent-generated databases places heavy strain on backend database provisioning infrastructure and compute capacity.
- Metacortex can assist in developing automated security scanning and linting tools within developer onboarding workflows to mitigate the fact that security auditors report widespread configuration pitfalls in user deployments such as exposed service keys in client bundles.
- Metacortex can augment the Multigres and platform engineering teams with distributed database reliability engineering, helping address the operational complexity and high-availability challenges of running and scaling PostgreSQL clusters at massive scale.
- Relevant case study: Scaling an event-analytics pipeline for a SaaS product (https://example.com/case-studies/event-analytics-scaling)
- How is the surge in agent-created databases impacting your provisioning latency, and where are the main bottlenecks appearing in the orchestration layer?
- What mechanisms or tooling are currently being prioritized to prevent common client-side credential misconfigurations before user projects reach production?
- With the development of Multigres, what architectural or operational challenges around distributed replication and failover could benefit most from external systems engineering support?

## What changed
- [Pending]

## Sources
- https://pitchbook.com/profiles/company/437773-51
- https://supabase.com/blog/supabase-series-e
- https://supabase.com/careers
- https://www.prnewswire.com/news-releases/supabase-announces-150m-in-new-funding-and-turso-acquisition-302896752.html
- https://supabase.com/blog/select-2026-operate-with-confidence
- https://supabase.com/blog/supabase-is-now-available-in-gemini-enterprise
- https://supabase.com/blog/introducing-osscar-index
- https://supabase.com/blog/categories/engineering
- https://supabase.com/blog/authors/ant_wilson
- https://supabase.com/blog/authors/joe_sciarrino
- https://supabase.com/blog/authors/sugu_sougoumarane
- https://www.trendingtopics.eu/supabase-150-million-turso/
- https://www.ddmarketer.com/gap/every-supabase-audit-finds-the-same-dozen-landmines-b0730f8a
- https://svpost.com/articles/supabase-500m-series-f/
- https://example.com/case-studies/event-analytics-scaling
