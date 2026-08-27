# ADR-003: Reusable durable job runner

## Decision

PursuitMap uses a local DuckDB-backed job runner for resumable background work. Source adapters provide job payloads and handlers. The runner owns job state, leases, retry scheduling, append-only events, and atomic progress sidecars.

## Scope

The runner supports API capture, source enrichment, document downloads, and document parsing. A source adapter remains responsible for request construction, response validation, and source-specific evidence.

## Rules

- Each job has a stable ID and one run ID.
- A running job has a lease. An expired lease returns to retryable work.
- Retryable failures use exponential backoff and jitter.
- A handler must return a `JobOutcome`.
- Every state change writes an event.
- Progress writes use a temporary file and atomic replacement.
- Existing run directories remain immutable during migration.

## Consequence

Future adapters can share execution behavior and tests. Existing runners migrate one adapter at a time. Each migration requires fixture tests and a new child run.
