# PursuitMap tool usage

Status: working document  
Last updated: 2026-08-27

This document records the commands and operating rules that have proved useful during source enrichment and document processing.

## Environment

Run Python commands through `mise` and `uv`:

```bash
cd /Users/steekam/Projects/pursuit-map
mise exec -- uv run pursuitmap <command>
```

Run the verification set before a commit:

```bash
mise exec -- uv run pytest -q
mise exec -- uv run python -m compileall -q pipeline/src tests
git diff --check
```

## Watch a workflow

Auto-select the newest run sidecar:

```bash
mise exec -- uv run pursuitmap watch
```

Watch a specific run:

```bash
mise exec -- uv run pursuitmap watch \
  --run-root data/enriched/south_africa/<run-id> \
  --interval 15
```

Show one update:

```bash
mise exec -- uv run pursuitmap watch \
  --run-root data/enriched/south_africa/<run-id> \
  --once
```

The watcher reads `progress.json`. It does not open DuckDB. Use the run-specific path when several workflows are active.

## South Africa coverage

Plan a child supervisor run from a completed bulk run:

```bash
mise exec -- uv run pursuitmap sa-api-supervise plan \
  --parent-run-id <bulk-run-id>
```

Resume an existing run with the measured exact-detail setting:

```bash
mise exec -- uv run pursuitmap sa-api-supervise resume \
  --run-id <supervisor-run-id> \
  --rate 3 \
  --max-concurrency 4
```

Inspect status or the final report:

```bash
mise exec -- uv run pursuitmap sa-api-supervise status --run-id <run-id>
mise exec -- uv run pursuitmap sa-api-supervise report --run-id <run-id>
```

The measured setting applies to exact detail requests. Monthly and paginated list requests use the lower source policy recorded in the capacity probe report.

## Flush permanent failures

Requeue approved transient failure classes:

```bash
mise exec -- uv run pursuitmap sa-api-supervise flush \
  --run-id <run-id>
```

Flush selected classes:

```bash
mise exec -- uv run pursuitmap sa-api-supervise flush \
  --run-id <run-id> \
  --reason http_500 \
  --reason TimeoutError
```

The flush keeps the original event and adds a `requeued` event. Access failures, 404 responses, malformed JSON, and OCID validation failures remain terminal.

## Kenya source enrichment

```bash
mise exec -- uv run pursuitmap source-enrich plan ke --limit 25
mise exec -- uv run pursuitmap source-enrich run ke --run-id <run-id>
mise exec -- uv run pursuitmap source-enrich resume ke --run-id <run-id>
mise exec -- uv run pursuitmap source-enrich status ke --run-id <run-id>
```

Use the Kenya supervisor command when a long run needs recovery:

```bash
mise exec -- uv run pursuitmap source-enrich supervise ke \
  --run-id <run-id> \
  --max-cycles 250
```

## Document downloads and parsing

Plan and run binary capture:

```bash
mise exec -- uv run pursuitmap documents plan \
  --input-parquet <input.parquet> \
  --output-root <document-run> \
  --source-run-id <source-run-id> \
  --source-snapshot-sha256 <snapshot-sha256>

mise exec -- uv run pursuitmap documents run \
  --run-root <document-run>
```

Parse captured content hashes once:

```bash
mise exec -- uv run pursuitmap documents parse \
  --run-root <document-run>
```

The downloader and parser use the reusable DuckDB job runner. The parser also writes `document_runner_progress.json`. Content hashes prevent duplicate processing.

## Safe operating rules

1. Read the sidecar before starting or resuming a process.
2. Confirm that no worker is active for the same run.
3. Reuse valid cache entries before sending requests.
4. Keep parent runs immutable.
5. Preserve raw responses, hashes, and validation results.
6. Use reason-based failure flushes for transient classes only.
7. Read reports after materialization.
8. Commit code and documentation in separate atomic changes when they have separate purposes.

## Evidence locations

- Run progress: `<run-root>/progress.json`
- Generic runner progress: `<run-root>/document_runner_progress.json`
- Durable runner ledger: `<run-root>/document_jobs.duckdb`
- API supervisor ledger: `<run-root>/ledger.duckdb`
- Raw response files: `<run-root>/responses/`
- Captured document files: `<run-root>/files/`
- Run reports: `<run-root>/*_report.json` and `<run-root>/*_report.md`
- Architecture decisions: `docs/architecture/`
- Measured changes: `docs/build-log/`
