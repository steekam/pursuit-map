# Source-preserving enrichment schema

`quality_flags.parquet` is a derived observation table. It does not replace canonical OCDS values.

| Column | Meaning |
| --- | --- |
| `source_snapshot_sha256` | Raw snapshot hash. |
| `country` | Source country code. |
| `ocid`, `release_id` | Source lifecycle keys where available. |
| `table_name` | Canonical table that produced the observation. |
| `source_record_key` | Stage record key, such as `tender_id` or `contract_id`. |
| `source_field_path` | OCDS path used by the rule. |
| `flag_code` | Stable quality rule name. |
| `flag_status` | Observation state. Current rules use `observed`. |
| `observed_value_raw` | Original canonical value or status. |
| `rule_version` | Version of the enrichment rules. |
| `enrichment_run_id` | Run that created the row. |
| `generated_at` | UTC generation time. |

The Kenya rules record missing, invalid, or structurally absent source values. They do not fill values, convert currencies, merge entities, or infer procurement need.
