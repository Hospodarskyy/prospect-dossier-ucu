# Plausible Analytics

## Snapshot
- Plausible Analytics is an independent, open source analytics company based in the European Union. (https://plausible.io/about)
- Plausible Analytics has an operating team size of 11 people. (https://plausible.io/about)
- Plausible Analytics is self-funded, profitable, and operates without outside investors. (https://plausible.io/about)
- Plausible Analytics is completely owned by its co-founders. (https://plausible.io/blog/bootstrapping-saas)
- Plausible Analytics has more than 22,000 paying subscribers. (https://plausible.io/about)

## Recent news
- [Pending]

## Tech signals
- Plausible Analytics builds on a stack that includes Elixir, Phoenix, React, PostgreSQL, ClickHouse, and Docker. (https://plausible.io/jobs/product-engineer)
- Plausible Analytics deploys workloads using Docker on Hetzner Cloud servers and self-hosts its ClickHouse database. (https://plausible.io/jobs/infrastructure-engineer)

## Key people
- Uku Taht, Co-founder (https://plausible.io/blog/bootstrapping-saas)
- Marko Saric, Co-founder (https://plausible.io/blog/startup-marketing)

## Likely pains
- Plausible Analytics determined that standard open-source licenses do not provide sufficient protection against external commercial threats. (https://plausible.io/blog/community-edition)
- Plausible Analytics encounters high switching costs when attempting to persuade prospective customers to migrate from legacy analytics platforms. (https://plausible.io/blog/august-2020-recap)
- Plausible Analytics excludes deep product analytics features such as heatmaps and individual visitor tracking by design. (https://plausible.io/when-not-to-use-plausible)
- Plausible Analytics cannot rely on traditional paid advertising due to its high cost and conflict with privacy principles. (https://plausible.io/blog/blog-post-changed-my-startup)
- Hypothesis: Plausible faces the recurring risk of third parties commercializing its open-source codebase without contributing to development or driving cloud subscription revenue. (based on: Plausible Analytics determined that standard open-source licenses do not provide sufficient protection against external commercial threats) (https://plausible.io/blog/community-edition)
- Hypothesis: High switching friction keeps mainstream website operators tied to Google Analytics unless triggered by specific privacy compliance mandates. (based on: Plausible Analytics encounters high switching costs when attempting to persuade prospective customers to migrate from legacy analytics platforms) (https://plausible.io/blog/august-2020-recap)
- Hypothesis: Plausible's intentional lack of granular visitor tracking and session replay prevents it from winning product analytics deals in mature digital product teams. (based on: Plausible Analytics excludes deep product analytics features such as heatmaps and individual visitor tracking by design) (https://plausible.io/when-not-to-use-plausible)
- Hypothesis: Avoiding paid performance marketing limits customer acquisition velocity relative to venture-funded alternatives. (based on: Plausible Analytics cannot rely on traditional paid advertising due to its high cost and conflict with privacy principles) (https://plausible.io/blog/blog-post-changed-my-startup)

## Metacortex angle
- Metacortex can assist Plausible in engineering automated multi-server deployments and infrastructure orchestration for Docker on Hetzner, reducing operational burden for their lean 11-person team (relies on the fact that Plausible deploys workloads using Docker on Hetzner Cloud servers and has an operating team size of 11 people).
- Metacortex can help optimize and horizontally scale Plausible's self-hosted ClickHouse analytical database and ingestion pipeline as query loads and event volumes grow across 22,000+ paying subscribers (relies on the fact that Plausible self-hosts its ClickHouse database and has more than 22,000 paying subscribers).
- Metacortex can build specialized migration tooling and automated ingestion bridges from legacy platforms to ease migration friction for prospective customers (relies on the fact that Plausible encounters high switching costs when attempting to persuade prospective customers to migrate from legacy analytics platforms).
- Case study: "Container orchestration for a self-hosted product" (https://example.com/case-studies/container-orchestration)
- Case study: "Scaling an event-analytics pipeline for a SaaS product" (https://example.com/case-studies/event-analytics-scaling)
- How much operational engineering time does your team dedicate to maintaining plain Docker setups and ClickHouse nodes on Hetzner?
- Which automated migration features or data connectors would most effectively reduce switching barriers for teams migrating from legacy tools?
- At over 22,000 subscribers, what performance or infrastructure challenges are you anticipating in your analytical data layer over the coming year?

## What changed
- No material changes since 2026-11-11.

## Sources
- https://plausible.io/about
- https://plausible.io/blog/bootstrapping-saas
- https://plausible.io/jobs/product-engineer
- https://plausible.io/jobs/infrastructure-engineer
- https://plausible.io/blog/startup-marketing
- https://plausible.io/blog/community-edition
- https://plausible.io/blog/august-2020-recap
- https://plausible.io/when-not-to-use-plausible
- https://plausible.io/blog/blog-post-changed-my-startup
- https://example.com/case-studies/container-orchestration
- https://example.com/case-studies/event-analytics-scaling
