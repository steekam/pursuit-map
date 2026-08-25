# Kenya partition discovery

## 2026-08-25 — planner added

The historical recovery gap remains separate from the completed enrichment run. The new partition planner creates an immutable run with a new run ID and a DuckDB ledger.

Measured design rules:

- route: `/api/closed-tenders`;
- date filters: exact `published_at` and `close_at`;
- date selection: earliest, median, latest, and highest-frequency date per year;
- metadata filters: tender reference, title, buyer, procurement method, and category;
- request ceiling: 250 planned jobs;
- detail requests: zero during capture;
- mapping acceptance: both `id` and `ocid` are required;
- prior runs and raw response artifacts remain unchanged.

The planner uses the existing browser-compatible request headers, cache, retry policy, `Retry-After` handling, jitter, and 429 circuit breaker through the tested discovery executor.

Fixture verification passed for immutable run IDs, closed-route-only jobs, partition labeling, and the request cap.
