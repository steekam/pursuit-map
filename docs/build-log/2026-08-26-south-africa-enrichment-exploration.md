# 2026-08-26 — South Africa enrichment exploration

## Scope

The exploration tested the official South African eTenders OCDS API against the current OCP bulk snapshot. The probe used read-only requests and did not modify canonical data.

- API: `https://ocds-api.etenders.gov.za`
- API specification: `/swagger/v1/swagger.json`
- Baseline snapshot: `a79b2ce7dccdd7f060d4d4745c1207693c2c5acb7a9fc8fdf9ddd578893d2a01`
- Canonical records: 37,894 tenders

## Endpoints tested

### Paged release endpoint

`GET /api/OCDSReleases`

The specification exposes:

- `PageNumber`;
- `PageSize`;
- `dateFrom`;
- `dateTo`.

A January 2026 probe returned a valid OCDS release package. The response contained one release for the tested date window.

### Exact OCID endpoint

`GET /api/OCDSReleases/release/{ocid}`

A lookup for baseline OCID `ocds-9t57fa-100002` returned HTTP 200 and a release object. The join key is the exact canonical OCID. No suffix inference or name matching is required.

## Enrichment yield

The API response exposed fields that the current canonical tender table does not materialize as columns:

- tender province;
- delivery location;
- special conditions;
- contact person name, email, telephone, and fax;
- briefing-session status, compulsory flag, date, and venue;
- tenderers;
- top-level initiation type and language;
- party directory details, including legal name, address, and contact point;
- award and contract nested fields not currently represented in the canonical tables.

The current canonical tables already retain the raw release JSON. The enrichment value therefore comes from validated field-specific derived columns and cross-snapshot comparison, not from replacing raw records.

## Candidate enrichment tables

The next adapter should materialize separate tables:

`sa_api_release_observations`

- source API URL;
- retrieval timestamp;
- response checksum;
- source snapshot hash;
- OCID;
- API release ID and release date;
- raw response path;
- validation status.

`sa_api_tender_details`

- OCID and release ID;
- province;
- delivery location;
- special conditions;
- contact fields;
- briefing-session fields;
- tenderers JSON;
- API response provenance.

`sa_api_party_details`

- OCID;
- party ID and role;
- legal name;
- address fields;
- contact fields;
- API response provenance.

The adapter must keep API observations separate from canonical OCDS values. A row becomes accepted only when the response OCID equals the requested OCID and the raw response has a checksum.

## What this can improve

- ICT retrieval can use delivery location, special conditions, and tenderer context.
- Buyer follow-up can use API contact fields where present.
- Eligibility review can use special conditions and compulsory briefing-session status.
- Geographic analysis can use province and delivery location.
- Party auditing can compare supplier names, legal names, roles, and contact details.
- Release-history analysis can compare bulk and API release dates and field values.

## Limits found

- One API response does not establish field coverage for the full snapshot.
- The API may contain current values that differ from the immutable bulk snapshot.
- API award schema details do not include every lifecycle field needed for complete outcome analysis.
- The bulk source still has zero plan items, missing award dates, 171 missing contract period starts, and 4,326 supplier ID `0` rows.
- The API does not remove the need for document acquisition and evidence extraction.

## Decision

The SA API is a viable deterministic enrichment source. The exact OCID endpoint should be the first implementation path. A staged pilot should fetch 25, 100, and 1,000 canonical OCIDs selected by stable hash, then compare field coverage and value drift before wider capture.

The adapter should reuse the existing durable request pattern: DuckDB ledger, immutable raw responses, retry policy, response checksums, OCID validation, progress sidecar, and run manifests.
