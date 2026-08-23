# Canonical schema contract

Every canonical Parquet table includes `source_snapshot_sha256`. Lifecycle rows retain `ocid` and `release_id`. Nested source objects remain in `raw_json` when present.

## Tables

| Table | Grain | Purpose |
| --- | --- | --- |
| `releases` | one source release | Release history and source provenance. |
| `buyers` | one source buyer ID/name pair | Buyer identity observations. Entity merging is deferred. |
| `suppliers` | one source supplier ID/name pair | Supplier identity observations. Entity merging is deferred. |
| `procurement_plans` | one planning object per release | Plan presence, rationale, budget, period, and item count. |
| `procurement_plan_items` | one published plan item | Detailed planned procurement, when the publisher supplies items. |
| `tenders` | one tender object per release | Solicitation, category, method, dates, value, and procuring entity. |
| `awards` | one award per release | Award outcome and value. |
| `award_suppliers` | one award-supplier link | Explicit award-to-supplier bridge. |
| `contracts` | one contract per release | Contract signature, period, value, and award link. |
| `documents` | one document metadata record | Evidence metadata and source URL. |
| `identity_audit` | one entity identity observation | Placeholder, collision, and variant diagnostics. |

## Field semantics

- `*_raw` preserves the source representation.
- Parsed dates use UTC ISO-8601 strings. A sibling `*_status` records `valid`, `missing`, `invalid`, or `sentinel`.
- Amounts preserve the source amount and currency. `value_status` records `valid`, `zero`, `negative`, `invalid`, or `missing`.
- `identifier_status` records `present`, `missing`, or `placeholder`.
- Empty tables are valid observations. A zero row count does not prove zero procurement activity.

## Provenance

Run manifests under `data/working/south_africa/runs/` record the source hash, transformation version, environment, output checksums, query or rule version, and warnings. Search results add `ocid`, release ID, source field paths, and document URLs to the evidence bundle.
