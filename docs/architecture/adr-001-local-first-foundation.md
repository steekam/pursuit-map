# ADR-001 — local-first procurement foundation

## Decision

Use Python, DuckDB, and Parquet for Phase 0 and Phase 1 ingestion, normalization, inspection, and descriptive analysis. Store the downloaded source as an immutable local artifact. Store derived tables separately.

## Why

The initial source fits local analytical processing. DuckDB runs SQL over Parquet without a separate service. Parquet keeps canonical outputs portable and inspectable. A serving database can consume materialized results after the domain and data-quality questions are clear.

## Consequences

- The same raw artifact and code produce deterministic re-runs.
- Git excludes raw files and generated outputs.
- Source hashes and manifests trace each experiment.
- Entity resolution, retrieval, scoring, and serving remain later phases.
