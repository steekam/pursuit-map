# PursuitMap

PursuitMap turns public procurement data into evidence-backed commercial lead discovery. Phase 0/1 begins with South African OCDS data from National Treasury's eTender publication.

## Local workflow

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

pursuitmap ingest za
pursuitmap normalize za
pursuitmap profile za
pursuitmap materialize za
pursuitmap search za --query "network modernization" --vertical ict --limit 20 --format json
```

The raw artifact is kept under `data/raw/` with a SHA-256 manifest. Each normalization run writes canonical Parquet under `data/parquet/south_africa/<normalize-run-id>/` and DuckDB under its matching run directory. Reports, derived marts, and run manifests are also physically versioned; compatibility files at the data root point to the latest result. Generated data is gitignored. The latest canonical run is selected by `data/working/south_africa/normalization_manifest.json`.

## Current scope

This repository currently establishes the procurement domain map, source ingestion, canonical lifecycle tables, deterministic identity auditing, descriptive marts, and explainable ICT retrieval. It does not implement fuzzy entity resolution, document downloading, semantic embeddings, lead scoring, a hosted database, or a product UI.
