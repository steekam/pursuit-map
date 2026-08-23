# Kenya PPIP source notes

## Source

PursuitMap pulled the all-time Kenya PPRA/PPIP OCDS JSONL gzip snapshot from the OCP Data Registry.

- Registry page: <https://data.open-contracting.org/en/publication/147>
- Publisher endpoint: <https://tenders.go.ke/ocds>
- Coverage reported by the registry: July 2018 to July 2026
- Registry update frequency: daily
- OCID prefix: `ocds-5whusi`
- Local snapshot size: 42,345,300 bytes
- Local snapshot SHA-256: `5501335abfb5dc1dacb90bbc156c4a97e45bc59c5e4c499c845ca748ad025b97`

The local manifest is `data/raw/kenya/manifest.json`. Raw files remain outside version control.

## Raw profile

| Measure | Kenya snapshot |
| --- | ---: |
| Compiled releases | 259,132 |
| Releases with `ocid` | 259,132 |
| Releases with `id` | 259,132 |
| Releases with `date` | 259,132 |
| Tender objects | 259,132 |
| Tender periods with start date | 258,887 |
| Tender periods with end date | 258,887 |
| Awards | 109,125 |
| Award-supplier links | 79,832 |
| Contracts | 109,125 |
| Planning objects | 0 |
| Tender, award, and contract items | 0 |
| Documents | 0 |
| Tender values with amount | 0 |
| Award values with amount | 109,125 |
| Contract values with amount | 109,125 |
| Buyer IDs missing | 0 |
| Buyer names missing | 0 |
| Supplier IDs missing or equal to `0` in award rows | 0 |

The profile counts raw JSON fields. They do not certify identifier validity or field correctness.

## Registry quality warnings

The OCP registry reports these issues:

- `awards` and `contracts` can be empty arrays.
- The top 1% of award and contract values contain extreme outliers.
- Supplier identifiers use an invalid organization identifier scheme.
- Buyers have no organization identifier scheme.
- `parties` can omit buyer and supplier names. The names appear in `buyer.name` and `awards.supplier.name`.
- Planning, documents, items, transactions, milestones, amendments, and extensions have zero reported records.

## Initial comparison with South Africa

| Measure | South Africa baseline | Kenya snapshot | Reading |
| --- | ---: | ---: | --- |
| Compiled releases | 37,894 | 259,132 | Kenya has more process records in the retrieved snapshot. |
| Planning objects | 37,894 | 0 | South Africa has planning objects. Kenya does not provide planning in this export. |
| Planning items | 0 | 0 | Neither source supports plan-item analysis in this snapshot. |
| Tender objects | 37,894 | 259,132 | Kenya has broader tender volume. |
| Awards | 11,187 | 109,125 | Kenya has more award rows. |
| Contracts | 1,653 | 109,125 | Kenya reports a contract row for every award row. |
| Documents | 43,421 | 0 | South Africa supports document metadata analysis. Kenya does not in this export. |
| Tender period coverage | 37,894 / 37,894 | 258,887 / 259,132 | Kenya has 245 tender records without both period dates. |
| Supplier identity warning | 4,326 placeholder supplier rows | Invalid supplier identifier scheme | Both sources require identity review. |

The comparison supports a Kenya adapter experiment. Kenya is useful for tender, award, contract, and timing analysis. South Africa remains stronger for planning and document metadata. The sources should remain separate until canonical mapping and source-specific quality checks exist.

Run the current raw-source report with:

```bash
uv run pursuitmap profile ke
```

The report uses the shared JSON and Markdown shape. It marks the profile as `raw_source` and reports a warning because canonical relationship checks are not available yet.

## Scope decision

Keep Kenya as a source-comparison track. Do not merge Kenya and South Africa into one baseline. Build a country-specific adapter after this raw profile, then compare canonical field coverage with the same quality report contract.
