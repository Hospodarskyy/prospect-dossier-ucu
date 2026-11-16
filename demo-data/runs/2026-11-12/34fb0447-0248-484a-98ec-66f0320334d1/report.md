# Plausible Analytics

## Snapshot
- Plausible Analytics is an independent, open-source web analytics company based in the European Union. (https://plausible.io/about)
- The company is completely self-funded and operates profitably without outside investors. (https://plausible.io/about)
- Plausible operates with a team of 11 people. (https://plausible.io/about)
- More than 22,000 paying customer subscribers use Plausible. (https://plausible.io/about)

## Recent news
- [Pending]

## Tech signals
- Plausible self-hosts its ClickHouse database and PostgreSQL instances. (https://plausible.io/jobs/infrastructure-engineer)
- Plausible deploys workloads using Docker on Hetzner Cloud servers running Ubuntu. (https://plausible.io/jobs/infrastructure-engineer)
- Plausible's self-hosted Community Edition is distributed under the AGPLv3 open-source license. (https://plausible.io/when-not-to-use-plausible)

## Key people
- Uku Taht, Design and Development (https://plausible.io/docs/authors)
- Marko Saric, Marketing and Communication (https://plausible.io/docs/authors)

## Likely pains
- Aggressive ad blockers can block Plausible despite its privacy-friendly model because they target all analytics tools indiscriminately. (https://plausible.io/blog/do-ad-blockers-block-plausible-analytics)
- Vertically scaling single servers reached operational limits under high-volume event ingestion. (https://plausible.io/jobs/infrastructure-engineer)
- Providing technical support to open-source self-hosters in the same manner as paying subscribers proved impossible to sustain. (https://plausible.io/blog/scaling-customer-support)
- Standard Google Analytics remains available without any subscription fee. (https://plausible.io/blog/google-analytics-pricing)
- Hypothesis: Scaling the ingestion pipeline horizontally across clusters presents complex architectural and operational demands for a small engineering team. (based on: Vertically scaling single servers reached operational limits under high-volume event ingestion.) (https://plausible.io/jobs/infrastructure-engineer)
- Hypothesis: Maintaining the free self-hosted Community Edition creates non-revenue-generating support overhead that risks pulling engineering resources away from paying SaaS customers. (based on: Providing technical support to open-source self-hosters in the same manner as paying subscribers proved impossible to sustain.) (https://plausible.io/blog/scaling-customer-support)
- Hypothesis: Plausible faces constant positioning hurdles having to persuade prospective customers to pay for analytics when Google Analytics provides standard web analytics for free. (based on: Standard Google Analytics remains available without any subscription fee.) (https://plausible.io/blog/google-analytics-pricing)
- Hypothesis: Ad blockers blocking Plausible's script by default lead to data underreporting concerns and increased customer support inquiries. (based on: Aggressive ad blockers can block Plausible despite its privacy-friendly model because they target all analytics tools indiscriminately.) (https://plausible.io/blog/do-ad-blockers-block-plausible-analytics)

## Metacortex angle
- Metacortex can assist Plausible in designing and implementing a horizontally distributed ingestion architecture to overcome the operational limits encountered when vertically scaling single cloud servers (relying on: Vertically scaling single servers reached operational limits under high-volume event ingestion).
- Metacortex can help automate container orchestration and infrastructure as code across Hetzner Cloud infrastructure, reducing maintenance burdens on a lean 11-person team (relying on: Plausible deploys workloads using Docker on Hetzner Cloud servers running Ubuntu).
- Metacortex can advise on custom proxy and edge configurations to help customers preserve ingestion fidelity against indiscriminate ad blockers (relying on: Aggressive ad blockers can block Plausible despite its privacy-friendly model because they target all analytics tools indiscriminately).
- Case study: Scaling an event-analytics pipeline for a SaaS product (https://example.com/case-studies/event-analytics-scaling)
- Case study: Container orchestration for a self-hosted product (https://example.com/case-studies/container-orchestration)
- What architectural bottlenecks are currently appearing first in your ClickHouse setup as event ingestion scales?
- How is your team currently approaching horizontal clustering and failover across Hetzner servers?
- Would offloading infrastructure orchestration and database clustering allow your core engineering team to focus more on product features for paying subscribers?

## What changed
- No material changes since 2026-11-11.

## Sources
- https://plausible.io/about
- https://plausible.io/jobs/infrastructure-engineer
- https://plausible.io/when-not-to-use-plausible
- https://plausible.io/docs/authors
- https://plausible.io/blog/do-ad-blockers-block-plausible-analytics
- https://plausible.io/blog/scaling-customer-support
- https://plausible.io/blog/google-analytics-pricing
- https://example.com/case-studies/event-analytics-scaling
- https://example.com/case-studies/container-orchestration
