# Phase 1.5 checkpoint assessment

Date: 2026-08-25

Decision: continue with a constrained evidence-backed procurement discovery product.

## Measured facts

### Foundation

- South Africa baseline: 37,894 releases, 37,894 tenders, 11,187 awards, 1,653 contracts, and 43,421 document records.
- Canonical normalization, source manifests, DuckDB storage, Parquet outputs, quality reports, and deterministic retrieval are implemented.
- The test suite has 49 passing tests.
- Atomic commits preserve implementation checkpoints.

### Kenya enrichment

- Canonical snapshot size: 259,132 records.
- Combined validated OCIDs: 16,742.
- Validated coverage: 6.46%.
- Historical archive detail validation: 32 accepted of 69 candidates before rate limiting. Remaining jobs are resumable.
- The PPIP source has a durable request ledger, raw response storage, OCID validation, retry policy, rate-limit handling, and progress sidecars.
- The current source remains strong for recent records and weak for older records.

### Documents

- Unique attachment URLs planned: 50,292.
- Files captured in the bounded pilot: 96.
- Unique binaries parsed with Docling: 95.
- Rule occurrences: 17,628.
- Evidence completeness: 17,628/17,628 (100%).
- Documents with observed features: 59.
- Documents with no observed rule features: 36.
- Conflicts: 550.
- Ambiguities: 550.
- These counts describe extraction observations. They do not measure field accuracy.

### Classification

- Three GPT-5.4 mini workers and three GPT-5.6 Luna high workers classified the same 95 binaries.
- Role agreement: 92/95 (96.84%).
- Standardization-flag agreement: 91/95 (95.79%).
- The main roles are tender notices, tender documents, correspondence, meeting minutes, and evaluation records.
- Framework agreements show high within-role text similarity in a two-document sample.
- Tender documents show moderate within-role similarity.
- Tender notices show low within-role similarity.
- A large cross-role cluster shows that procurement boilerplate can create false similarity.

## Value delivered

The document layer adds scope and requirement evidence that the canonical Kenya data lacks:

- eligibility requirements in 40 documents;
- submission deadlines in 31 documents;
- evaluation criteria in 24 documents;
- technical specifications in 22 documents;
- quantities in 21 documents;
- bid-security amounts in 21 documents;
- warranty periods in 21 documents;
- ICT terms in 32 documents;
- networking terms in 12 documents.

These fields support procurement discovery, requirement review, evidence-backed summaries, and supplier-fit research. They do not support supplier quality claims, win probabilities, market-share estimates, or commercial forecasts.

## Risks and gaps

- Kenya mapping coverage remains 6.46%.
- Planning data is weak or absent.
- Supplier identity contains placeholder IDs.
- Contract timing has missing and sentinel values.
- Document rules overmatch some fields. `consultant_name` produced 2,299 occurrences and requires tightening.
- Thirty-six documents produced no observed features. These may reflect sparse content, scan quality, or unsupported roles.
- Agent classifications are stable across two passes, yet they are not ground truth.
- The current document sample is too small for broad source-level conclusions.
- No human-reviewed retrieval gold set exists.

## Viability decision

The project remains viable for:

- evidence-backed procurement discovery;
- historical procurement analysis;
- deterministic retrieval experiments;
- document-based requirement summaries;
- source-quality measurement.

The project is not ready for:

- predictive opportunity scoring;
- supplier quality or win-likelihood claims;
- broad Kenya historical coverage claims;
- automated document-derived decisions without review.

## Next gate

1. Create a human-reviewed document gold set. Sample each major role and all three classification disagreements.
2. Review the highest-volume noisy rules, starting with `consultant_name`, `document_role`, and `document_title`.
3. Add role-conditioned rule profiles and compare field coverage before and after refinement.
4. Build a reviewed retrieval challenge set.
5. Reassess value after measuring field agreement and retrieval stability.

The next gate should decide whether to expand document acquisition, improve historical mapping, or invest in entity review. The current evidence supports continued work on the discovery layer.
