# South Africa procurement source and schema notes

## Source selected

PursuitMap starts with National Treasury's Office of the Chief Procurement Officer (OCPO) data published through the eTender Publications Portal and exposed in OCDS format.

- Transparency portal: <https://data.etenders.gov.za/>
- OCDS API documentation: <https://ocds-api.etenders.gov.za/swagger/index.html>
- OCP Data Registry publication: <https://data.open-contracting.org/en/publication/143>
- OCDS standard: <https://standard.open-contracting.org/latest/en/>

The registry describes compiled contracting-process records available from February 2017 onward, with JSONL, CSV, and Excel bulk formats. The raw ingestion currently uses the registry's full JSONL gzip artifact and records its URL, retrieval time, byte size, and SHA-256 hash in `data/raw/south_africa/manifest.json`.

## Source shape observed/documented

Each JSONL object is treated as a compiled OCDS release when it is a direct object. If a future source artifact contains a package with a `releases` array, ingestion expands that array into individual releases. The useful first-level fields are:

| OCDS field | PursuitMap use | Notes |
| --- | --- | --- |
| `ocid` | Contracting-process key | Stable process identifier; expected prefix `ocds-9t57fa`. |
| `id` | Release key | Identifies a published release/version. |
| `date` | Source release timestamp | Carried into canonical lifecycle and relationship tables as `release_date`. |
| `tag` | Lifecycle marker | Distinguishes planning, tender, award, contract, and implementation updates. |
| `buyer` | Buyer identity | Use `buyer/id` and `buyer/name`; do not merge names across IDs yet. |
| `parties` | Party directory | Useful when present; registry notes it is absent for many records. |
| `planning` | Procurement-plan signal | Includes budget, rationale, documents, and sometimes items. |
| `tender` | Tender advertisement | Includes title, description, status, method, category, periods, value, and documents. |
| `awards` | Award outcome | Includes award value/date/status and supplier references. |
| `contracts` | Contract stage | Includes award link, signature date, period, value, and documents. |
| `documents` | Evidence/provenance | Retain URLs and metadata in a bridge table. |

The source registry currently reports no tender, award, or contract items in its summary. The pipeline still captures item arrays when present so this absence is measured rather than baked into the domain model.

## Known source limitations

The publisher coverage is not a complete census of South African procurement. It depends on entities sharing data with National Treasury, and the registry notes exclusions and voluntary participation. The registry also reports duplicate releases, empty fields/arrays, invalid placeholder values, and missing `parties` arrays. These are source observations, not normalization errors.

## Initial canonical mapping

| Canonical dataset | Source paths | Identity rule in Phase 1 |
| --- | --- | --- |
| `buyers` | `buyer.id`, `buyer.name` | Keep source ID/name pairs. Normalize whitespace/case into a comparison field; no entity merge. |
| `suppliers` | `awards[].suppliers[].id/name` | Keep source ID/name pairs. No entity merge. |
| `procurement_plans` | `planning` | One row per release containing a planning object; preserves rationale, budget, period, and raw planning JSON. |
| `procurement_plan_items` | `planning.items[]` | One row per item, linked to `ocid` and `release_id`. |
| `tenders` | `tender` | One row per release containing a tender object. |
| `awards` | `awards[]` | One row per award, linked to `ocid` and `release_id`. |
| `award_suppliers` | `awards[].suppliers[]` | Bridge between awards and supplier identities. |
| `contracts` | `contracts[]` | One row per contract, linked to `ocid`, `release_id`, and `awardID`. |
| `documents` | `planning.documents[]`, `tender.documents[]`, `awards[].documents[]`, `contracts[].documents[]` | Evidence rows linked to `ocid` and `release_id`. |

Values preserve source amounts and currencies, with explicit `missing`, `invalid`, `zero`, `negative`, and `valid` statuses. OCDS `startDate`/`endDate` fields are retained as raw strings and parsed into UTC ISO-8601 values. `0001-01-01` sentinel dates remain flagged rather than treated as real dates.

## Uncertain mappings to revisit

- A plan may be represented in `planning` without `planning.items`; absence is not evidence that no plan exists.
- A compiled release can represent the latest known state of a process, while release history is carried by separate releases/API responses. Phase 1 must decide whether to deduplicate by `ocid`, preserve every release, or maintain both views.
- `buyer` and award `suppliers` are procurement-process roles. `parties` is a broader directory and should not be treated as a complete buyer/supplier master.
- OCDS `tender.mainProcurementCategory` is useful for coarse classification, but it is not yet PursuitMap's ICT/networking/cybersecurity capability taxonomy.
