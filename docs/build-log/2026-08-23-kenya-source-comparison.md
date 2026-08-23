# 2026-08-23 — Kenya source comparison

## Hypothesis

The Kenya PPRA/PPIP OCDS export can extend PursuitMap's country coverage. Its raw field coverage must be measured before adapter work begins.

## Work

Pulled the OCP Data Registry all-time Kenya JSONL gzip snapshot. Recorded its URL, retrieval time, size, and SHA-256 hash in the ignored raw-data manifest. Profiled release, lifecycle, planning, item, document, timing, value, and identity fields.

## Measurement

The snapshot contains 259,132 compiled releases, 259,132 tenders, 109,125 awards, 109,125 contracts, and 79,832 award-supplier links. It contains 0 planning objects, 0 items, and 0 documents. Tender start and end dates are present in 258,887 records. Tender amounts are absent. Award and contract amounts are present in 109,125 rows each.

South Africa has 37,894 releases, 37,894 tenders, 11,187 awards, 1,653 contracts, 37,894 planning objects, and 43,421 documents in the current baseline. Tender periods are populated for all 37,894 tender rows.

## Observation

Kenya has greater tender, award, and contract volume. South Africa has richer planning and document metadata. Kenya's export reports one contract row for every award row. The registry reports an invalid supplier identifier scheme, no buyer identifier scheme, extreme value outliers, and missing party names.

The raw profile found no missing buyer IDs or names and no supplier IDs equal to `0`. These counts do not prove that the identifiers are valid or stable.

## Decision

Keep Kenya as a separate comparison track. Build a country-specific adapter after the raw profile. Compare canonical coverage and warnings with the existing South Africa quality report.

## Next

1. Add Kenya source configuration and an ingestion command.
2. Normalize Kenya into the shared lifecycle schema with source-specific warnings.
3. Run the same integrity and quality checks for both countries.

## Publication

private
