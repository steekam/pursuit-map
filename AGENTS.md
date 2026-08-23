# PursuitMap operating contract

Read this file before changing the repository. Keep changes within the current phase unless the user explicitly expands scope.

## Source and truth rules

- Treat the hashed OCP South Africa bulk snapshot as the Phase 1 baseline source.
- Preserve raw source artifacts and raw JSON. Never replace raw values with parsed or normalized values.
- Keep missing, invalid, sentinel, zero, negative, and placeholder values distinct.
- Every canonical or derived output must retain source snapshot hash, run ID, and the relevant source keys.
- Use deterministic transformations. Scores are retrieval or rule scores, never probabilities or predictions.
- Do not add fuzzy matching, embeddings, LLM extraction, document downloading, lead scoring, API services, or browser UI in Phase 1–1.5.

## Data and run rules

- Canonical Parquet and DuckDB outputs belong under a unique normalization run directory.
- Derived marts and reports belong under their operation run directory.
- Compatibility files may point to the latest run; they must not be the only copy.
- Do not commit raw or generated data. Record hashes and row counts in manifests.
- Before changing a schema, update `config/pipeline-contract.json`, canonical schema documentation, and tests together.

## Development loop

1. Read the relevant ADR and contract entry.
2. Make one cohesive change.
3. Run `uv run pytest -q`, `uv run python -m compileall -q pipeline/src tests`, and `git diff --check`.
4. Run the affected CLI command against a fixture, then the current snapshot when practical.
5. Commit one logical change with an imperative message. Do not use checkpoint commits.

## Useful commands

```bash
uv run pursuitmap ingest za
uv run pursuitmap normalize za
uv run pursuitmap verify za
uv run pursuitmap profile za
uv run pursuitmap materialize za
uv run pursuitmap search za --query "network modernization" --vertical ict --format json
```

The contract is machine-readable in `config/pipeline-contract.json`. The canonical schema and decision history live under `docs/`.
