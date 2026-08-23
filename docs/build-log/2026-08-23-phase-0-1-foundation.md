# 2026-08-23 — Phase 0 and Phase 1 foundation

## Hypothesis

The South African National Treasury OCDS publication is accessible in a compact, machine-readable format. It can support the first local canonical data layer.

## Work

Created a Python project with CLI commands for ingestion, normalization, profiling, materialization, and deterministic ICT retrieval. Added raw-source manifests, release history, corrected OCDS date and value semantics, identity audits, DuckDB normalization, Parquet tables, descriptive marts, evidence-bearing search results, schema contracts, verification checks, domain notes, and architecture decisions.

## Measurement

The downloaded snapshot is 13,330,673 bytes with SHA-256 `a79b2ce7dccdd7f060d4d4745c1207693c2c5acb7a9fc8fdf9ddd578893d2a01`. It contains 37,894 releases, 741 distinct buyer ID/name pairs, 9,121 distinct supplier ID/name pairs, 37,894 planning rows, 0 planning items, 37,894 tenders, 11,187 awards, 1,653 contracts, and 43,421 documents. Corrected tender periods now cover the source records; 171 contract period starts are missing/sentinel. Main procurement category is populated for 29,917 tenders with three values: services, goods, and works. The deterministic ICT baseline currently returns 7,529 candidates. Baseline candidate counts are 286 for title-only, 4,775 for title+description, 4,575 for title+description+category, and 7,529 for full metadata.

## Observation

The registry identifies incomplete publisher coverage, duplicate releases, empty or invalid fields, and frequent absence of `parties`. Source identifiers remain separate from future entity resolution. The snapshot contains no `planning.items` rows, although planning objects are present. Supplier ID `0` appears in 4,326 award-supplier rows. 173 contract period fields are sentinel or missing. The pipeline reports both conditions as warnings.

## Decision

Use the registry's full JSONL gzip artifact. Keep lifecycle relationships in explicit `award_suppliers` and `documents` tables. Use source-field lexical rules for the first retrieval baseline. Defer entity merging, document downloads, and learned opportunity scoring.

## Next

Next, compare deterministic retrieval baselines. Add a reviewed query challenge set. Measure the value of document acquisition and entity-resolution work before selecting the next phase.

## Publication

private
