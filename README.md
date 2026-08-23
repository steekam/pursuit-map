# PursuitMap

PursuitMap studies public procurement data for evidence-backed commercial lead discovery. Phase 0 and Phase 1 use South African OCDS data from National Treasury's eTender publication.

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

The project environment is `.venv/` at the repository root. `uv.lock` records the dependency resolution. Run commands with `uv run`.

The repository is a monorepo. Python data production lives under `pipeline/`. Shared project assets remain at the root. Future serving and product applications will become separate workspace members when they contain working code.

```text
pipeline/       Python ingestion, normalization, verification, and materialization
analytics/      SQL and exploratory analysis
config/         Taxonomies and machine-readable contracts
data/           Raw, canonical, working, and materialized outputs
docs/           Domain, architecture, build log, and artifacts
tests/          Cross-project and pipeline tests
```

The raw artifact is stored under `data/raw/` with a SHA-256 manifest. Each normalization run writes canonical Parquet under `data/parquet/south_africa/<normalize-run-id>/`. The matching DuckDB file is under the run directory. Reports, marts, and manifests use versioned run directories. Compatibility files point to the latest result. Git ignores generated data. `data/working/south_africa/normalization_manifest.json` selects the latest canonical run.

Cross-session operating rules live in [`AGENTS.md`](AGENTS.md). The machine-readable pipeline contract is [`config/pipeline-contract.json`](config/pipeline-contract.json); tests enforce its required layers, operations, determinism, and boundaries.

Project phase status and next decisions are tracked in [`docs/roadmap/phase-tracker.md`](docs/roadmap/phase-tracker.md).

## Current scope

The repository currently provides the procurement domain map, source ingestion, canonical lifecycle tables, deterministic identity audits, descriptive marts, and explainable retrieval for ICT. It has no fuzzy entity resolution, document download, semantic embedding, lead scoring, hosted database, or product UI.
