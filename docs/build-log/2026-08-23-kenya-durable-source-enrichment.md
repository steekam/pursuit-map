# Kenya durable source enrichment

Date: 2026-08-23

## Implementation

The Kenya PPIP adapter now uses a DuckDB request ledger, immutable JSON response files, list-based ID-to-OCID mappings, OCID validation, retry classification, rate limiting, and resumable runs.

Commands:

```text
pursuitmap source-enrich plan ke --limit 25
pursuitmap source-enrich run ke --run-id <run-id>
pursuitmap source-enrich resume ke --run-id <run-id>
pursuitmap source-enrich report ke --run-id <run-id>
```

`enrich-source` remains a compatibility alias for a planned and executed run.

## Pilot evidence

The first live 25-limit run completed after list pagination:

| Measure | Result |
| --- | ---: |
| Unique list mappings | 300 |
| Canonical matches | 48 |
| Accepted detail rows | 48 |
| Successful requests | 51 |
| Permanent failures | 0 |
| Retryable failures | 0 |
| Duplicate mappings | 0 |
| Detail OCID match rate | 100% |
| Effective request rate | 0.79 requests/second |

Detail field coverage:

- title: 48/48;
- procuring entity name: 48/48;
- procuring entity PIN: 37/48;
- procurement method: 48/48;
- procurement category: 48/48;
- publication date: 48/48;
- close date: 48/48;
- financial year: 48/48;
- attachment metadata: 48/48.

The run was resumed after implementation changes. It produced the same logical accepted detail rows and closed accounting.

## Limits

Live portal behavior remains time-dependent. The ledger records request attempts, status codes, retries, response hashes, raw paths, and unmatched canonical records. No document binary was downloaded. Full historical coverage remains gated behind the 100, 1,000, and full rollout stages.
