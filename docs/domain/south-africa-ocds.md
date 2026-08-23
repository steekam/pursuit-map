# South Africa procurement source and schema notes

## Source selected

PursuitMap uses National Treasury's Office of the Chief Procurement Officer (OCPO) data. The eTender Publications Portal publishes the data in OCDS format.

- Transparency portal: <https://data.etenders.gov.za/>
- OCDS API documentation: <https://ocds-api.etenders.gov.za/swagger/index.html>
- OCP Data Registry publication: <https://data.open-contracting.org/en/publication/143>
- OCDS standard: <https://standard.open-contracting.org/latest/en/>

The registry describes compiled contracting-process records from February 2017 onward. It provides JSONL, CSV, and Excel bulk formats. Raw ingestion uses the full JSONL gzip artifact. The ingestion manifest records its URL, retrieval time, byte size, and SHA-256 hash in `data/raw/south_africa/manifest.json`.

## Source shape observed/documented

Ingestion treats each direct JSONL object as a compiled OCDS release. If a future artifact contains a package with a `releases` array, ingestion expands the array into individual releases. The main first-level fields are:

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

The source registry currently reports no tender, award, or contract items in its summary. The pipeline captures item arrays when present. The output can therefore measure item coverage.

## Known source limitations

The publisher coverage is not a complete census of South African procurement. It depends on entities sharing data with National Treasury. The registry notes exclusions and voluntary participation. It also reports duplicate releases, empty fields or arrays, invalid placeholder values, and missing `parties` arrays. These conditions come from the source.

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

- A plan can contain `planning` without `planning.items`. The absence of items does not prove that no plan exists.
- A compiled release can represent the latest known process state. Separate releases or API responses can carry release history. Phase 1 must choose whether to deduplicate by `ocid`, preserve every release, or maintain both views.
- `buyer` and award `suppliers` describe procurement-process roles. `parties` describes a broader directory. Treat it as an incomplete buyer and supplier reference.
- OCDS `tender.mainProcurementCategory` supports coarse classification. PursuitMap's ICT, networking, and cybersecurity capability taxonomy remains derived.
