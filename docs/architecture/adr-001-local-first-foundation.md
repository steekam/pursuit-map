# ADR-001 — local-first procurement foundation

## Decision

Use Python, DuckDB, and Parquet for Phase 0/1 ingestion, normalization, inspection, and descriptive analytics. Preserve the downloaded source as an immutable local raw artifact and write derived tables separately.

## Why

The initial source is small enough for local analytical processing. DuckDB provides SQL over Parquet without introducing a service. Parquet keeps canonical analytical outputs portable and inspectable. A later serving database can consume materialized results after the domain and data-quality questions are understood.

## Consequences

- Re-runs are deterministic given the same raw artifact and code.
- Raw files and generated outputs stay out of version control.
- Source hashes and manifests make experiments traceable.
- Entity resolution, retrieval, scoring, and serving remain later phases.
