# PostHog
Note: the research did not fully pass verification; some topics may be incomplete.

## Snapshot
- PostHog is an open-source platform for building software products. (https://posthog.com/hogpedia/posthog)
- PostHog operates as a fully remote company with staff distributed internationally across more than 20 countries. (https://posthog.com/handbook/company/culture)
- PostHog employs around 200 people remotely. (https://getleadwave.io/dossier/posthog)
- PostHog was part of Y Combinator's Winter 2020 batch and has raised funding from Stripe, GV, and Y Combinator. (https://posthog.com/media)

## Recent news
- PostHog announced updated events data retention for new paid plans, lowering default retention to 2 years from 7 years. (date: 2026-11-05) (https://posthog.com/blog/events-data-retention-update)
- PostHog announced that select event properties will be retained for only 60 days before deletion to accelerate query performance. (date: 2026-10-27) (https://posthog.com/blog/changing-event-storage)

## Tech signals
- PostHog core framework and application technologies include Django, React, and TypeScript. (https://posthog.com/handbook/engineering/developer-experience)
- PostHog utilizes Docker Compose alongside PostgreSQL and ClickHouse for managing its core data stack. (https://posthog.com/handbook/engineering/developing-locally)
- PostHog runs background AI sandboxed agents inside isolated cloud containers with access to codebase execution and data. (https://posthog.com/handbook/engineering/ai/sandboxed-agents)

## Key people
- James Hawkins, Co-CEO (https://posthog.com/about)
- Tim Glaser, Co-CEO (https://posthog.com/about)
- Judy Opperwall, Office Manager (https://posthog.com/handbook/people/hogpatch)

## Likely pains
- PostHog views scaling its data pipeline as its primary challenge while distributing pipeline ownership to autonomous small teams. (https://posthog.com/handbook/story)
- PostHog finds scaling an engineering organization harder than scaling sales due to high coordination complexity and overlapping work. (https://posthog.com/handbook/finance)
- PostHog faces complexity maintaining consistency across multiple product comparison matrices against market alternatives. (https://posthog.com/handbook/engineering/posthog-com/product-comparisons)
- Hypothesis: Rapidly rising event volumes create continuous infrastructure cost pressure and data warehouse pipeline bottlenecks. (based on: The biggest challenge is scaling our data pipeline, and making sure we give as much responsibility as we can to each small team) (https://posthog.com/handbook/story)
- Hypothesis: Scaling decentralized autonomous engineering teams risks duplicated code paths, architectural drift, and cross-team alignment hurdles. (based on: The disadvantage is that scaling an engineering team is, in our opinion, harder than scaling a sales team.) (https://posthog.com/handbook/finance)
- Hypothesis: Offering an all-in-one suite forces constant product maintenance to match specialized point-solution competitors across numerous distinct categories. (based on: Keeping product comparison charts up-to-date across a large website with multiple products is tricky, so we've built a way to source data) (https://posthog.com/handbook/engineering/posthog-com/product-comparisons)

## Metacortex angle
- Metacortex can provide specialized engineering capacity for ClickHouse query performance tuning and high-throughput data pipelines, directly supporting PostHog where it views scaling its data pipeline as its primary challenge while distributing pipeline ownership to autonomous small teams.
- Metacortex can assist autonomous feature teams by developing robust, reusable integration scaffolding and shared internal tooling, addressing the hypothesis that scaling decentralized autonomous engineering teams risks duplicated code paths, architectural drift, and cross-team alignment hurdles.
- Case study: Scaling an event-analytics pipeline for a SaaS product (https://example.com/case-studies/event-analytics-scaling) demonstrates Metacortex's experience helping an analytics SaaS resolve single-node database limits under increasing event volume via horizontally scalable ingestion and storage architectures.
- Which specific areas of the ClickHouse ingestion pipeline currently create the largest performance or maintenance hurdles for your small autonomous teams?
- How do you balance platform-level engineering efforts against product feature velocity across your expanding suite of developer tools?
- What architectural adjustments are planned to manage query latency and storage overhead as customer event retention policies evolve?

## What changed
- [Pending]

## Sources
- https://posthog.com/hogpedia/posthog
- https://posthog.com/handbook/company/culture
- https://getleadwave.io/dossier/posthog
- https://posthog.com/media
- https://posthog.com/blog/events-data-retention-update
- https://posthog.com/blog/changing-event-storage
- https://posthog.com/handbook/engineering/developer-experience
- https://posthog.com/handbook/engineering/developing-locally
- https://posthog.com/handbook/engineering/ai/sandboxed-agents
- https://posthog.com/about
- https://posthog.com/handbook/people/hogpatch
- https://posthog.com/handbook/story
- https://posthog.com/handbook/finance
- https://posthog.com/handbook/engineering/posthog-com/product-comparisons
- https://example.com/case-studies/event-analytics-scaling
