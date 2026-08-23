# Kenya PPIP HAR investigation

Date: 2026-08-23

## Result

The PPIP portal exposes public JSON endpoints. A HAR captured from the tender list, closed-tender list, contracts page, and one tender detail page confirmed these routes:

| Endpoint | Role |
| --- | --- |
| `/api/active-tenders` | Active tender list. |
| `/api/closed-tenders` | Closed tender list. |
| `/api/tender/{id}` | Tender detail record. |
| `/api/explore-contracts` | Contract exploration data. |
| `/api/get/all/published-contracts` | Published contract list. |
| `/api/agpogroup/all` | AGPO group reference data. |

The list responses include both `id` and `ocid`. The detail response includes procurement method and category, procuring entity data, dates, fee, validity, financial year, reservation groups, and document metadata.

## Validation finding

The numeric suffix in a Kenya OCID cannot be treated as the PPIP internal ID. A 100-record pilot using that assumption produced:

| Measure | Result |
| --- | ---: |
| Requested | 100 |
| Attempted | 87 |
| Valid detail records | 0 |
| HTTP 404 | 47 |
| HTTP 429 | 26 |
| HTTP 200 with wrong OCID | 14 |

The adapter rejected wrong-OCID responses. It remains uncommitted.

## Selected deterministic flow

```text
capture active/closed list response
→ persist {id, ocid} mapping and response checksum
→ join mapping to the canonical Kenya snapshot
→ request /api/tender/{id}
→ validate returned ocid
→ persist raw response and checksum
→ write source enrichment rows
```

The same captured list and detail responses produce identical enrichment output. Live portal runs remain time-varying and must retain retrieval timestamps, status codes, response hashes, and failed-request records.

## Pagination capability audit

The captured HAR shows list parameters for search, page size, ordering, tender reference, title, buyer, procurement method, procurement category, close date, publication date, and addenda. A live read-only probe confirmed that `perpage=5000` is accepted. The closed list reports 142,900 records over 29 pages at that size; the active list reports 303 records on one page. Exact `published_at` and `close_at` filters also work. Comma-separated date ranges returned zero records and remain unsupported.

New Kenya enrichment runs use `perpage=5000`. Existing runs retain their original page size and remain resumable.

HAR artifacts:

- `data/enriched/kenya/ppip-portal.har`
- `data/enriched/kenya/ppip-closed.har`

These files remain outside version control with other generated data.
