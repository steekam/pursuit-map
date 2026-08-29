# 2026-08-29 — South Africa supervisor throughput

## Observation

The supervisor was configured for 3 requests per second and concurrency 8. Completion measured about 12.2 jobs per minute because batch processing waited for slow requests and retries.

## Change

The supervisor now refills worker slots when a request finishes. It fetches a queue of pending jobs and submits the next job as each worker becomes available. The existing rate limiter remains shared across workers.

The event ledger now records:

- request elapsed seconds;
- transport attempts used by the shared HTTP client.

## Safety

- The source rate remains controlled by the shared limiter.
- The capacity probe still selects the highest healthy concurrency.
- The current run directory was not modified.
- The change applies when a new supervisor process starts or resumes.

## Verification

- Full test suite: 64 passed.
- Compile check passed.
- `git diff --check` passed.
