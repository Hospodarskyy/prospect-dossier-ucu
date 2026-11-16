# Plausible Analytics

## Snapshot
- Plausible Analytics is an independent, open source web analytics company based in the European Union. (https://plausible.io/about)
- Plausible is incorporated as a legal entity in Estonia. (https://plausible.io/eu-hosted-web-analytics)
- Plausible is operated by a team of 11 people. (https://plausible.io/about)
- Plausible is self-funded, profitable, and operates without outside investors. (https://plausible.io/about)
- More than 22,000 paying subscribers use Plausible. (https://plausible.io/about)

## Recent news
- [Pending]

## Tech signals
- Plausible has closed applications for its product engineering role. (https://plausible.io/jobs/product-engineer)
- Plausible uses Elixir and the Phoenix framework in its tech stack. (https://plausible.io/jobs/product-engineer)
- Plausible uses PostgreSQL for relational data and ClickHouse for analytical data. (https://plausible.io/jobs/product-engineer)
- Plausible uses GitHub Actions and Docker for CI and builds, alongside Terraform and Ansible for deployments. (https://plausible.io/jobs/product-engineer)
- Plausible deploys workloads using plain Docker on Hetzner Cloud servers running Ubuntu. (https://plausible.io/jobs/infrastructure-engineer)

## Key people
- Uku Taht, Design and development (https://plausible.io/docs/authors)
- Marko Saric, Marketing and communication (https://plausible.io/docs/authors)
- Cenk, Infrastructure and security (https://plausible.io/docs/authors)
- Bogdan, Customer success (https://plausible.io/docs/authors)
- Sanne, Product designer (https://plausible.io/docs/authors)

## Likely pains
- Automated scrapers, bots, and AI crawlers cause traffic spikes that pollute web analytics. (https://plausible.io/blog/spike-in-website-traffic)
- Multi-site management is cumbersome when users must be invited individually on a per-site basis. (https://feedback.plausible.io/269)
- Plausible faced threats from corporations exploiting its open-source code without contributing back. (https://plausible.io/blog/community-edition)
- Ingesting high volumes of events led Plausible to reach the limits of vertically scaling cloud servers. (https://plausible.io/jobs/infrastructure-engineer)
- Hypothesis: Plausible faces increasing pressure to invest engineering resources into automated bot and scraper detection to keep client metrics reliable. (based on: Automated scrapers, bots, and AI crawlers cause traffic spikes that pollute web analytics.) (https://plausible.io/blog/spike-in-website-traffic)
- Hypothesis: Plausible faces recurring operational tension protecting its open-source intellectual property from commercial exploitation by competitors. (based on: Plausible faced threats from corporations exploiting its open-source code without contributing back.) (https://plausible.io/blog/community-edition)
- Hypothesis: Plausible requires complex infrastructure re-architecting to scale horizontally as event ingestion expands across high-traffic clients. (based on: Ingesting high volumes of events led Plausible to reach the limits of vertically scaling cloud servers.) (https://plausible.io/jobs/infrastructure-engineer)
- Hypothesis: Plausible faces friction retaining large agency and enterprise customers whose workflows require centralized multi-site user management. (based on: Multi-site management is cumbersome when users must be invited individually on a per-site basis.) (https://feedback.plausible.io/269)

## Metacortex angle
- Metacortex can assist Plausible in designing a horizontal scaling architecture for ClickHouse and event processing to overcome the limits of vertical cloud server upgrades (relying on: Ingesting high volumes of events led Plausible to reach the limits of vertically scaling cloud servers).
- Metacortex can help introduce robust container orchestration and infrastructure automation to replace manual Docker setups across Hetzner nodes (relying on: Plausible deploys workloads using plain Docker on Hetzner Cloud servers running Ubuntu).
- Metacortex can support engineering teams in building automated bot and scraper detection pipelines to filter illegitimate traffic spikes (relying on hypothesis: Plausible faces increasing pressure to invest engineering resources into automated bot and scraper detection to keep client metrics reliable).
- Case study: Scaling an event-analytics pipeline for a SaaS product (https://example.com/case-studies/event-analytics-scaling)
- Case study: Container orchestration for a self-hosted product (https://example.com/case-studies/container-orchestration)
- How is Plausible currently planning the architectural transition from single vertically-scaled servers to distributed event ingestion?
- What techniques are being explored to mitigate automated bot and crawler traffic spikes without impacting ingestion latency?
- Would adopting container orchestration simplify deployment workflows and server management across Hetzner Cloud infrastructure?

## What changed
- No material changes since 2026-11-12.

## Sources
- https://plausible.io/about
- https://plausible.io/eu-hosted-web-analytics
- https://plausible.io/jobs/product-engineer
- https://plausible.io/jobs/infrastructure-engineer
- https://plausible.io/docs/authors
- https://plausible.io/blog/spike-in-website-traffic
- https://feedback.plausible.io/269
- https://plausible.io/blog/community-edition
- https://example.com/case-studies/event-analytics-scaling
- https://example.com/case-studies/container-orchestration
