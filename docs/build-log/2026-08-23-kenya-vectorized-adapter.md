# Kenya vectorized canonical adapter

Date: 2026-08-23

## Decision

Use DuckDB JSON staging and SQL lifecycle expansion for large JSONL sources. The adapter stages each source object once, expands awards, suppliers, and contracts with `json_each`, and writes the canonical Parquet tables and DuckDB database.

The South Africa Python path remains unchanged. Kenya uses the adapter through the normal `pursuitmap normalize ke` command.

## Evidence

Source snapshot SHA-256: `5501335abfb5dc1dac90bbc156c4a97e45bc59c5e4c499c845ca748ad025b97`

Measured canonical counts:

| Table | Rows |
| --- | ---: |
| releases | 259,132 |
| tenders | 259,132 |
| awards | 109,125 |
| contracts | 109,125 |
| award_suppliers | 79,832 |
| buyers | 1,208 |
| suppliers | 63,939 |
| procurement_plans | 0 |
| procurement_plan_items | 0 |
| documents | 0 |

The output schema matches the versioned canonical table contract. The verification report passes schema, duplicate-key, supplier-link, and snapshot-hash checks. It reports 21 contract references without a matching award. These references remain in the contract table and are visible as a source-quality warning.

## Limits

The adapter preserves source values. It does not repair dates, infer tender values, merge entities, or create missing documents and planning records.
