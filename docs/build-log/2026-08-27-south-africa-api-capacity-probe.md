# 2026-08-27 — South Africa API capacity probe

## Scope

The probe tested the official South Africa eTenders OCDS API with a separate ledger and response store. The active enrichment run was not changed.

- Snapshot: `a79b2ce7dccdd7f060d4d4745c1207693c2c5acb7a9fc8fdf9ddd578893d2a01`
- Probe run: `sa-api-probe-20260827T103617Z-a79b2ce7dccd`
- Stage 1: 1 request/second, concurrency 1
- Workload: exact OCID detail, small monthly list, paginated monthly list, and a slow historical monthly list

## Result

Stage 1 reached a source boundary. Eight exact OCID requests and one small monthly request validated. The paginated 2021 request returned HTTP 500. The May 2021 request timed out. The stage stopped before higher-rate testing, as required by the safety gate.

The earlier exact-only probe passed all eight configured stages through 4 requests/second and concurrency 4. That result applies to the exact detail endpoint sample. It does not establish a safe rate for list endpoints.

## Decision

Use separate policies by request class:

- exact detail: 3 requests/second and concurrency 4, subject to a new production child-run validation;
- list and historical windows: retain 1 request/second and concurrency 1 until the 500 response and timeout receive a source-specific investigation.

The probe does not establish a global API limit. It establishes endpoint-specific behavior for the tested samples.

## Artifacts

- `data/enriched/south_africa/sa-api-probe-20260827T103617Z-a79b2ce7dccd/sa_api_capacity_probe_report.json`
- `data/enriched/south_africa/sa-api-probe-20260827T103617Z-a79b2ce7dccd/sa_api_capacity_probe_results.parquet`
- `data/enriched/south_africa/sa-api-probe-20260827T103617Z-a79b2ce7dccd/sa_api_capacity_probe_headers.parquet`

The probe stores failed responses and request headers. It does not infer that a timeout means a missing record.
