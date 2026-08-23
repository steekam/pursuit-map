# Kenya detail-request capacity benchmark

Date: 2026-08-24

The benchmark used 60 verified PPIP IDs from the optimized enrichment ledger. It saved every response body, checksum, HTTP status, and OCID validation result.

| Request rate | Workers | Valid responses | 429 responses | Result |
| ---: | ---: | ---: | ---: | --- |
| 1/sec | 1 | 20/20 | 0 | pass |
| 2/sec | 2 | 20/20 | 0 | pass |
| 4/sec | 4 | 19/20 | 1 | warn |

The provisional production ceiling is 2 requests per second. The current engine remains single-worker, so this change increases the refill rate without enabling untested concurrent writes or response processing. Four-worker execution is not promoted because the sample produced a 429 response.

Benchmark artifact:

`data/enriched/kenya/source-capacity-20260823T223344Z/capacity_report.json`

This is a bounded capacity result. Re-test after source behavior, network conditions, or request policy changes.
