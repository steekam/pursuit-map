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

## 2026-08-25 — bounded pilot result

Run: `mapping-partition-20260825T121141950643Z-5501335abfb5`

- planned jobs: 250;
- successful responses: 38;
- permanent failures: 212;
- retryable or pending jobs at close: 0;
- response artifacts: 38;
- distinct response checksums: 38;
- candidate mapping observations: 439;
- unique candidate OCIDs: 423;
- new canonical matches: 419;
- duplicate observations: 2;
- detail requests: 0;
- document downloads: 0.

Exact `published_at` filters produced 24 successful responses. Exact `close_at` filters produced 14 successful responses. Date-plus-buyer, tender-reference, title, procurement-method, and category filters produced no successful responses in this pilot. The report records these filter results separately.

The successful responses recovered historical candidates across 2018–2025. Counts by canonical release year were 23, 54, 78, 22, 30, 10, 95, and 110 for 2018 through 2025. These are candidate mappings. Detail OCID validation remains required before enrichment promotion.

The 212 failed jobs were classified as `URLError`. The run preserved the successful raw responses and failure events. The result supports a targeted detail-validation sample. It does not justify an exhaustive historical date crawl yet.
