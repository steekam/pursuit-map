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

# Kenya source profile
uv run pursuitmap ingest ke
uv run pursuitmap profile ke
```

The project environment is `.venv/` at the repository root. The project pins UV 0.10.6 in `.mise.toml`. `uv.lock` records the dependency resolution. Run commands with `uv run`.

The repository is a monorepo. Python data production lives under `pipeline/`. Shared project assets remain at the root. Future serving and product applications will become separate workspace members when they contain working code.

Document capture uses the durable downloader before Docling extraction:

```text
uv run pursuitmap documents plan --input-parquet <source-enrichment.parquet> --output-root <document-run> --source-run-id <run-id> --source-snapshot-sha256 <hash>
uv run pursuitmap documents run --run-root <document-run>
uv run pursuitmap documents extract --run-root <document-run> --rules-path config/document-extraction/rules.json
uv run pursuitmap documents report --run-root <document-run>
```

```text
pipeline/       Python ingestion, normalization, verification, and materialization
analytics/      SQL and exploratory analysis
config/         Taxonomies and machine-readable contracts
data/           Raw, canonical, working, and materialized outputs
docs/           Domain, architecture, build log, and artifacts
tests/          Cross-project and pipeline tests
```

The raw artifact is stored under `data/raw/` with a SHA-256 manifest. Each normalization run writes canonical Parquet under `data/parquet/south_africa/<normalize-run-id>/`. The matching DuckDB file is under the run directory. Reports, marts, and manifests use versioned run directories. Compatibility files point to the latest result. Git ignores generated data. `data/working/south_africa/normalization_manifest.json` selects the latest canonical run.

`pursuitmap profile ke` profiles the canonical Kenya snapshot. Use `pursuitmap source-enrich plan ke --limit 25` to create a resumable PPIP enrichment run.

Use `pursuitmap source-enrich supervise ke --run-id <run-id>` to resume the run after rate-limit or network pauses. The supervisor waits for the configured cooldown, records cycles in `supervisor.json`, and stops at its cycle or runtime bound. `pursuitmap source-enrich status ke --run-id <run-id>` reads the sidecars without opening DuckDB while a worker is active.

Use `pursuitmap source-enrich analyze ke --run-id <run-id>` to create the final quality comparison and release-month mapping-gap reports from the completed Parquet outputs.

Cross-session operating rules live in [`AGENTS.md`](AGENTS.md). The machine-readable pipeline contract is [`config/pipeline-contract.json`](config/pipeline-contract.json); tests enforce its required layers, operations, determinism, and boundaries.

Project phase status and next decisions are tracked in [`docs/roadmap/phase-tracker.md`](docs/roadmap/phase-tracker.md).

## Current scope

The repository currently provides the procurement domain map, source ingestion, canonical lifecycle tables, deterministic identity audits, descriptive marts, explainable retrieval for ICT, durable document capture, and rule-based document feature extraction. It has no fuzzy entity resolution, semantic embedding, lead scoring, hosted database, or product UI.
