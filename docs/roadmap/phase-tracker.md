# PursuitMap phase tracker

Last updated: 2026-08-23  
Current phase: Phase 1.5 — deterministic retrieval lab  
Overall status: Foundation complete. Evaluation and explorer work remain.

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
| Phase 1 — reproducible data foundation | complete | [canonical schema](../domain/canonical-schema.md), [quality report](../build-log/2026-08-23-phase-0-1-foundation.md), commits `78af6cb`, `183c975` | Whether document acquisition or entity review has higher value. |
| Phase 1 — descriptive analytics | complete | [descriptive SQL](../../analytics/queries/phase1_descriptive.sql), materialized marts, commit `4759e71` | Which explorer views deserve a product surface. |
| Phase 1.5 — deterministic retrieval lab | in progress | [ICT taxonomy](../../config/verticals/ict.json), [construction taxonomy](../../config/verticals/construction.json), [healthcare taxonomy](../../config/verticals/healthcare.json), [vertical comparison](../build-log/2026-08-23-vertical-comparison.md) | Build a reviewed challenge set before making accuracy claims. |
| Phase 1.5 — document feature review | pending human review | [document rule registry](../../config/document-extraction/rules.json), captured run `data/enriched/kenya/documents-source-enrich-20260823T174027305351Z-5501335abfb5` | Review all 17 content hashes and create the gold set. |
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
- The test suite has 13 passing tests.
- Cross-session rules live in [`AGENTS.md`](../../AGENTS.md) and [`pipeline-contract.json`](../../config/pipeline-contract.json).
- Kenya canonical normalization uses a DuckDB vectorized adapter and reconciles raw release, tender, award, contract, and award-supplier counts.

## Current gaps

- No human-reviewed retrieval gold set exists.
- Planning semantics remain weak. The current snapshot has 0 planning items.
- Supplier ID `0` remains in 4,326 award-supplier rows.
- Contract timing has 171 missing period starts and 173 sentinel or missing period fields.
- Document extraction produced 9,212 evidence occurrences across 17 content hashes. The report records 281 conflicts and 281 ambiguities. A conflict means a rule observed more than one normalized value for one feature in a document. An ambiguity means the primary-value rule could not select one value without risking an unsupported choice. These are review queues, not confirmed source errors.
- OCR provenance is unavailable in the existing Docling manifests. OCR-derived values remain unknown until page-level OCR status is captured.
- Kenya has 0 documents, 0 planning objects, 0 plan items, and 0 tender amounts in the canonical snapshot.
- Kenya quality flags are materialized in a source-preserving enrichment table with rule version `kenya-quality-1`.
- Kenya PPIP source enrichment has a durable DuckDB ledger and passed the first 25-limit pilot with 100% detail OCID validation.
- Entity merging, prediction, lead scoring, API, and browser UI are not implemented.

## Immediate next work

1. Human-review the 17 unique document hashes. For each document, verify role, tender number, dates, buyer, eligibility, technical scope, quantities, commercial terms, evaluation criteria, ICT terms, and page/table evidence.
2. Record reviewed values and page references in a gold file keyed by content hash. Keep conflicting and ambiguous occurrences visible beside the selected value.
3. Measure field-level agreement and evidence completeness. Do not call the result precision, recall, or commercial accuracy beyond this reviewed sample.
4. Create a small reviewed retrieval challenge set from fixtures and current-source candidates.
5. Compare title-only, title-plus-description, category, and full-metadata retrieval against the set.

Every completed step should update this tracker and add a build-log entry. The tracker records project state; the build log records the reasoning and measurements behind state changes.
