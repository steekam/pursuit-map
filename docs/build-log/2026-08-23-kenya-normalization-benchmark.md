# 2026-08-23 — Kenya normalization path benchmark

## Hypothesis

DuckDB's vectorized JSON reader and Parquet writer will process Kenya faster than Python row construction followed by row-by-row DuckDB inserts.

## Work

Compared two paths on the 259,132-release Kenya snapshot:

1. Current Python `iter_releases()` and `build_rows()` path.
2. DuckDB `read_json_objects()` with vectorized scalar extraction and Parquet output.

The benchmark is reproducible with:

```bash
uv run python pipeline/benchmarks/benchmark_normalization.py \
  --source data/raw/kenya/ocds_full.jsonl.gz
```

## Measurement

| Path | Releases | Rows or output | Time |
| --- | ---: | ---: | ---: |
| Python parse and row construction | 259,132 | 1,155,310 rows | 15.340 seconds |
| DuckDB vectorized extraction and Parquet write | 259,132 | 259,132 releases; 48,443,924 bytes | 1.846 seconds |

The earlier full Kenya normalization attempt used row-by-row `executemany()` inserts. It created a large staging database and did not finish in a practical time. The run was stopped and its incomplete outputs were removed.

## Decision

Use DuckDB vectorized JSON staging, SQL array expansion, and Parquet writes for Kenya canonical normalization. Keep Python for transformations that require complex evidence or identity logic. Use batch interfaces for those transformations.

## Constraints

- The benchmark measures scalar release extraction. It does not yet prove that every canonical nested relationship can be expressed in the proposed SQL path.
- The SQL path must preserve raw JSON, source keys, value semantics, date status, and provenance.
- Output row counts, warning counts, and logical checksums must match the current contract.

## Next

Implement the Kenya canonical adapter with vectorized staging. Benchmark full lifecycle expansion before changing the South Africa path.

## Publication

private
