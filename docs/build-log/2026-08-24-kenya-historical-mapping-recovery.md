# Kenya historical mapping recovery

Date: 2026-08-24

## Measured facts

- Source run: `source-enrich-20260824T134223819613Z-5501335abfb5`.
- Source snapshot: `5501335abfb5dc1dacb90bbc156c4a97e45bc59c5e4c499c845ca748ad025b97`.
- Discovery run: `mapping-discovery-20260824T162056291465Z-5501335abfb5`.
- Discovery cap: 250 jobs.
- Discovery result: 247 successful jobs and 3 timeout failures.
- Candidate mappings: 18,784.
- New canonical matches: 3,113.
- Duplicate observations: 23,345.
- Detail requests were excluded from discovery.
- Promotion child: `source-enrich-promotion-20260824T164142190128Z-5501335abfb5`.
- The child selected 1,481 new OCIDs for the bounded month-cohort sample.
- The first detail attempt accepted 87 responses, stored 87 raw responses, and recorded 3 HTTP 429 responses.
- The child run paused with 1,391 pending jobs and 3 retryable jobs.

## Decisions

- The completed baseline run remains immutable.
- Discovery responses remain separate from detail responses.
- A list mapping becomes enrichment only after detail response OCID validation.
- Duplicate mappings remain visible in discovery outputs.
- The rate policy pauses after three consecutive 429 responses. The pause remains visible in `progress.json` and the execution report.

## Limitations

- The bounded probe does not measure exhaustive historical coverage.
- A successful list response proves candidate mapping presence. It does not prove detail validity.
- The source returned rate-limit responses during promotion. The remaining sample requires controlled resume.
