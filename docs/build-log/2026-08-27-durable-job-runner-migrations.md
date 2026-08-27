# 2026-08-27 — Durable job runner migrations

## Decision

PursuitMap now has a reusable DuckDB-backed `DurableJobRunner`. Source adapters provide payloads and handlers. The runner records job state, leases, retry scheduling, append-only events, and atomic progress.

## Migrations

The document downloader and document parser use the runner in new or resumed runs.

- Downloader runner ledger: `document_runner_progress.json` plus `document_jobs.duckdb` tables.
- Parser runner ledger: `document_jobs.duckdb`.
- Existing download and extraction outputs remain content-addressed.
- Existing adapter-specific progress fields remain available.
- The active South Africa API run was not opened or modified.

## Verification

- Full test suite: 63 passed.
- Compile check passed.
- `git diff --check` passed.
- Atomic commits: `d5ef3ce`, `2137a82`, `5c15033`, `64d899e`.

## Remaining work

Kenya source enrichment still owns its existing list/detail ledger and retry loop. The migration must preserve list mappings, detail validation, cache reuse, eligibility states, and source-specific reports. The South Africa supervisor migration waits for the current run to finish or stop.
