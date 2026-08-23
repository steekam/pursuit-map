# PursuitMap

PursuitMap turns public procurement data into evidence-backed commercial lead discovery. Phase 0/1 begins with South African OCDS data from National Treasury's eTender publication.

## Local workflow

```bash
uv venv --python 3.12
uv sync

uv run pursuitmap ingest za
uv run pursuitmap normalize za
uv run pursuitmap profile za
uv run pursuitmap materialize za
uv run pursuitmap search za --query "network modernization" --vertical ict --limit 20 --format json
```

The project environment is `.venv/` at the repository root. `uv.lock` pins the reproducible dependency resolution; use `uv run ...` so commands use that environment without relying on a global virtualenv.

The raw artifact is kept under `data/raw/` with a SHA-256 manifest. Each normalization run writes canonical Parquet under `data/parquet/south_africa/<normalize-run-id>/` and DuckDB under its matching run directory. Reports, derived marts, and run manifests are also physically versioned; compatibility files at the data root point to the latest result. Generated data is gitignored. The latest canonical run is selected by `data/working/south_africa/normalization_manifest.json`.

Cross-session operating rules live in [`AGENTS.md`](AGENTS.md). The machine-readable pipeline contract is [`config/pipeline-contract.json`](config/pipeline-contract.json); tests enforce its required layers, operations, determinism, and boundaries.

## Current scope

This repository currently establishes the procurement domain map, source ingestion, canonical lifecycle tables, deterministic identity auditing, descriptive marts, and explainable ICT retrieval. It does not implement fuzzy entity resolution, document downloading, semantic embeddings, lead scoring, a hosted database, or a product UI.
