# PursuitMap phase tracker

Last updated: 2026-08-25
Current phase: Phase 1.5 — deterministic retrieval lab  
Overall status: Foundation complete. Discovery layer viable. Gold-set evaluation remains.

## Status vocabulary

- `complete` — The acceptance criteria are met. Evidence exists in the repository.
- `in progress` — Work has a bounded next step and partial evidence.
- `blocked` — Work needs a decision, data, or external dependency.
- `not started` — No implementation has begun.

## Phase overview

| Phase | Status | Evidence | Next decision |
| --- | --- | --- | --- |
| Phase 0 — domain and source understanding | complete | [domain glossary](../domain/glossary.md), [South Africa OCDS notes](../domain/south-africa-ocds.md), [ADR-001](../architecture/adr-001-local-first-foundation.md) | Keep South Africa as the baseline source for this milestone. |
| Kenya source comparison | complete | [Kenya PPIP source notes](../domain/kenya-ppip.md), [comparison build log](../build-log/2026-08-23-kenya-source-comparison.md), [normalization benchmark](../build-log/2026-08-23-kenya-normalization-benchmark.md), [adapter build log](../build-log/2026-08-23-kenya-vectorized-adapter.md) | Decide which source enrichments justify the next pipeline stage. |
| Kenya PPIP source enrichment | complete with warning | Fresh run `source-enrich-20260824T134223819613Z-5501335abfb5`, [quality report](../../data/enriched/kenya/source-enrich-20260824T134223819613Z-5501335abfb5/source_enrichment_quality_report.json), [mapping-gap report](../../data/enriched/kenya/source-enrich-20260824T134223819613Z-5501335abfb5/source_mapping_gap_report.json) | Historical recovery is a separate immutable run. |
| Kenya historical mapping recovery | archive and partition probes complete | Partition candidates were already covered by prior detail runs; archive detail run accepted 32 of 69 candidates before rate limiting; [partition report](../../data/enriched/kenya/mapping-partition-20260825T121141950643Z-5501335abfb5/mapping_partition_report.json) | Resume the 35 remaining archive detail jobs under the rate policy. |
| Phase 1 — reproducible data foundation | complete | [canonical schema](../domain/canonical-schema.md), [quality report](../build-log/2026-08-23-phase-0-1-foundation.md), commits `78af6cb`, `183c975` | Whether document acquisition or entity review has higher value. |
| Phase 1 — descriptive analytics | complete | [descriptive SQL](../../analytics/queries/phase1_descriptive.sql), materialized marts, commit `4759e71` | Which explorer views deserve a product surface. |
| Phase 1.5 — deterministic retrieval lab | in progress | [ICT taxonomy](../../config/verticals/ict.json), [construction taxonomy](../../config/verticals/construction.json), [healthcare taxonomy](../../config/verticals/healthcare.json), [vertical comparison](../build-log/2026-08-23-vertical-comparison.md) | Build a reviewed challenge set before making accuracy claims. |
| Phase 1.5 — document feature review | in progress | [document rule registry](../../config/document-extraction/rules.json), [checkpoint assessment](../checkpoints/2026-08-25-phase-1-5-assessment.md), Kenya run `data/enriched/kenya/documents-source-enrich-combined-20260825T133500Z` | Review the 95-document output, refine noisy rules, and create the gold set. |
| Phase 1.5 — Procurement Explorer | not started | — | Select the first explorer slice and its evidence contract. |
| Phase 2 — reviewed retrieval evaluation | not started | — | Compare lexical, BM25, embedding, or hybrid retrieval only after labels exist. |
| Phase 3 — entity-resolution study | not started | — | Decide whether deterministic review supports a bounded resolution experiment. |
| Phase 4 — qualified-opportunity demonstration | not started | — | Define opportunity, qualification, timing, and seller-fit evidence. |
| Phase 5 — historical backtest | not started | — | Establish temporal ground truth and leakage controls. |
| Phase 6 — live PursuitMap product | not started | — | Choose serving architecture after offline outputs stabilize. |
| Phase 7 — API/MCP/agent interface | not started | — | Expose the same evidence-backed resources through a stable contract. |
| Phase 8 — observability and experimentation | not started | — | Define production metrics and experiment boundaries. |
| Phase 9 — market validation | not started | — | Test product usefulness with real users and documented feedback. |

## Phase 1 acceptance evidence

- The source snapshot has a hash and manifest.
- The current baseline produces 37,894 releases, 37,894 tenders, 11,187 awards, 1,653 contracts, and 43,421 documents.
- Tender `startDate` and `endDate` mapping is corrected. Tender periods are populated.
- Canonical outputs use normalization run directories.
- Marts, reports, and retrieval outputs use operation run directories.
- Lifecycle integrity checks pass. Source-quality warnings remain visible.
- Deterministic ICT retrieval returns 7,529 candidates on the current snapshot.
- The test suite has 49 passing tests.
- Cross-session rules live in [`AGENTS.md`](../../AGENTS.md) and [`pipeline-contract.json`](../../config/pipeline-contract.json).
- Kenya canonical normalization uses a DuckDB vectorized adapter and reconciles raw release, tender, award, contract, and award-supplier counts.

## Current gaps

- No human-reviewed retrieval gold set exists.
- Planning semantics remain weak. The current snapshot has 0 planning items.
- Supplier ID `0` remains in 4,326 award-supplier rows.
- Contract timing has 171 missing period starts and 173 sentinel or missing period fields.
- Document extraction produced 17,628 evidence occurrences across 95 content hashes. The report records 550 conflicts and 550 ambiguities. A conflict means a rule observed more than one normalized value for one feature in a document. An ambiguity means the primary-value rule could not select one value without risking an unsupported choice. These are review queues, not confirmed source errors.
- OCR provenance is unavailable in the existing Docling manifests. OCR-derived values remain unknown until page-level OCR status is captured.
- Kenya has 0 documents, 0 planning objects, 0 plan items, and 0 tender amounts in the canonical snapshot.
- Kenya quality flags are materialized in a source-preserving enrichment table with rule version `kenya-quality-1`.
- Kenya PPIP source enrichment has a durable DuckDB ledger and passed the first 25-limit pilot with 100% detail OCID validation.
- The bounded historical discovery pilot captured 247 successful and 3 timed-out probes. It found 3,113 new canonical matches from 18,784 candidate mappings.
- Historical promotion uses a child ledger. The first child sample has 87 validated detail rows and 3 HTTP 429 responses. Pending jobs remain resumable.
- The first financial-year JSON continuation batch (`mapping-discovery-20260825T010320496668Z-5501335abfb5`) produced 1 successful page, 10 timeout failures, and 0 new mappings during a portal connectivity outage. The run is preserved for retry.
- Both promotion children passed. The latest combined view has 16,742 unique validated OCIDs, with 0 duplicate OCIDs. Coverage is 16,742/259,132 (6.46%).
- Entity merging, prediction, lead scoring, API, and browser UI are not implemented.

## Immediate next work

1. Human-review the 95-document classification and feature output, starting with the five low-confidence labels and three cross-pass disagreements.
2. Record reviewed values and page references in a gold file keyed by content hash. Keep conflicting and ambiguous occurrences visible beside the selected value.
3. Refine role-conditioned rules and re-run the document report.
4. Measure field-level agreement and evidence completeness. Do not call the result precision, recall, or commercial accuracy beyond this reviewed sample.
5. Create a small reviewed retrieval challenge set from fixtures and current-source candidates.
6. Compare title-only, title-plus-description, category, and full-metadata retrieval against the set.
7. Resume the historical promotion child run only after the document review gate is defined.

## Queued cleanup tasks

| Task | Status | Acceptance evidence |
| --- | --- | --- |
| Rename enrichment state `eligible` to `mapping_pending` | complete | Code, tests, and current Parquet output use the approved name; row counts and provenance are preserved. |
| Document the state transition rules for `mapping_pending`, `retry_later`, `validated_detail`, and `source_only` | in progress | Add the state definitions to the Kenya source notes. |
| Reconcile and re-materialize the current Kenya eligibility output after the rename | in progress | Re-run materialization, then record before/after counts and checksums. |

Every completed step should update this tracker and add a build-log entry. The tracker records project state; the build log records the reasoning and measurements behind state changes.
