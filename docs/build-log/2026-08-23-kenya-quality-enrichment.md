# Kenya source-preserving quality enrichment

Date: 2026-08-23

## Decision

Add `pursuitmap enrich ke` as a derived-observation stage after canonical normalization. It writes `quality_flags.parquet` under a versioned enrichment run directory. Canonical tables and raw snapshots remain unchanged.

## Evidence

Rule version: `kenya-quality-1`

The first run produced 1,164,575 flag rows:

| Flag | Rows |
| --- | ---: |
| `planning.object_absent` | 259,132 |
| `documents.object_absent` | 259,132 |
| `tender.description_missing` | 259,132 |
| `tender.value_missing` | 259,132 |
| `award.date_missing` | 109,125 |
| `contract.date_signed_missing` | 14,889 |
| `contract.period_start_missing_or_invalid` | 3,406 |
| `tender.period_start_missing_or_invalid` | 359 |
| `tender.period_end_missing_or_invalid` | 254 |
| `supplier.name_missing` | 14 |

Two runs produced identical logical flag rows after excluding run-specific provenance values.

## Limits

The flags describe availability and validity. They do not repair dates, fill values, resolve entities, or infer demand. Source enrichment remains a separate future step.
