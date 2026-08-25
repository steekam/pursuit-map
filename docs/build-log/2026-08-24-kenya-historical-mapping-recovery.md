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
- The first promotion child later completed with 1,481 validated rows.
- The remaining promotion child completed with 1,630 validated rows.
- Final combined materialization: 16,710 rows and 16,710 unique OCIDs.
- Financial-year Excel capture run: `contract-export-20260825T001259400434Z-5501335abfb5`.
- The capture stored 11 raw workbooks and 140,938 export rows.
- Exact tender-reference overlap with existing validated enrichment: 1,974 rows and 1,728 OCIDs.
- Accepted canonical additions from Excel: 0.
- Resumable JSON continuation run: `mapping-discovery-20260825T010320496668Z-5501335abfb5`.
- The continuation retried the eight prior failed pages and seeded the next page for each financial year.
- One page succeeded and 10 pages reached permanent `TimeoutError` after the configured retry limit.
- The continuation produced 0 candidate mappings and 0 new canonical matches.
- An independent 15-second connectivity check to the same endpoint returned HTTP 000 with 0 bytes.
- A retry was interrupted during another endpoint outage. The preserved ledger records 1 succeeded job, 4 permanent timeout failures, 5 retryable timeout failures, and 1 interrupted running job. No mappings were added.
- The discovery executor now resets interrupted `running` jobs with transient error classes during resume.
- The latest ordered retry cycle completed 3 pages, recorded 2 permanent timeout failures, and left 6 timeout pages retryable after the worker was stopped. Candidate mappings remained at 0 for this continuation run.
- A bounded IPv4 probe of failed page 23 waited 60 seconds and received 0 bytes. A five-second confirmation returned curl timeout 28 with HTTP 000 and 0 bytes. A known-good page still returned HTTP 200 in 0.57 seconds. The timeout remains page-specific upstream behavior.
- A route probe for failed page 23 with `perpage=5` also timed out after 20 seconds with 0 bytes. The timeout persisted after reducing the requested page size.
- Browser validation reached the Contracts view, selected financial year 2020/2021, and rendered page 23 of 693 with contract records. The portal UI therefore has a working path for the page that timed out in the direct client. Request-header or request-sequence differences remain unverified.
- Browser network capture later showed the page-23 request remained pending. Separate browser API calls returned HTTP 429 with `Retry-After: 8`, `X-RateLimit-Remaining: 0`, and a 60-request limit. After the cooldown, the browser received HTTP 200 for the initial contracts and explore requests. A direct page-23 request still timed out after 20 seconds, including the browser request marker and parameter order. The blocker has two parts: a server rate limit and a page-specific upstream timeout.
- The discovery client now sends the browser request marker and handles numeric or HTTP-date `Retry-After` values, adaptive slowdown, jitter, and circuit pauses. The fix is covered by 42 passing tests in commit `a11c6fd`.
- The fixed retry run completed with 3 succeeded pages and 8 permanent failures. Every failed job reached attempt 6. The run stored 3 response records with 3 distinct checksums and produced 0 candidate mappings. The refreshed report is `warn` with no retryable jobs.
- The eight failed pages are preserved as terminal failures for a later source investigation. The latest report is `warn` because the historical queue has unresolved pages.

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
- The bounded discovery run recovered 3,111 previously unvalidated canonical OCIDs. Two discovery matches were already covered elsewhere. The remaining 242,422 baseline `mapping_pending` records need a new source-discovery strategy.
- The Excel route has no OCID or tender ID. Its exact reference matches remain diagnostics until an OCID-bearing response validates each join. Current canonical coverage therefore remains 16,710 / 259,132 = 6.448%.

## 2026-08-25 — financial-year archive probe

Fresh run: `mapping-discovery-20260825T131416832813Z-5501335abfb5`.

- requests: 11, one initial page per financial year;
- successful responses: 11;
- raw responses: 11;
- distinct response checksums: 11;
- response bytes: 1,004,149;
- mapping observations: 74;
- unique candidate OCIDs: 74;
- new canonical candidates: 70;
- overlap with the partition pilot: 0 OCIDs.

The `/api/get/explored-contracts` route returned data for all 11 financial-year probes. The first page is capped at 10 records, so this result measures route access and first-page yield. It does not measure full financial-year coverage.

The existing Excel capture remains the broader contract-data source: 11 workbooks, 140,938 rows, and 1,728 exact references to 1,728 already validated OCIDs. The workbooks contain contract numbers, amounts, award and contract dates, buyer names, supplier names, procurement fields, and tender references. They contain no OCID or PPIP tender ID. Excel joins remain diagnostic until an OCID-bearing response validates them.

The next efficient step is to promote a deterministic sample from the 70 archive candidates and the 419 partition candidates. Keep the two source cohorts separate during validation.

## 2026-08-25 — document acquisition planning

The validated combined run contains 50,292 unique attachment URLs across 16,710 records. The downloader now supports a request limit and writes a `progress.json` sidecar after each job.

A 100-URL pilot was started at one request per second and stopped after 21 processed attempts because every attempt failed with DNS error `URLError: [Errno 8] nodename nor servname provided, or not known`. The pilot captured 0 files. The document ledger remains resumable with 50,279 pending jobs, 12 permanent failures, and 1 retryable failure.

The failure blocks network acquisition in the current environment. It does not establish that the document URLs are invalid. Resume the pilot after DNS access is restored, then evaluate content-type and binary success rates before a larger batch.

## 2026-08-25 — DNS root cause and recovery

The failure was isolated to the Codex sandbox runtime. The sandbox reported `No DNS configuration available`; Python and `curl` returned `nodename nor servname provided, or not known`. A network-enabled execution resolved `tenders.go.ke` through `192.168.100.1` to `197.254.120.51`, and HTTPS returned `200 OK`.

The project now provides `pursuitmap network-check`. Live source-enrichment and document-download CLI actions run the preflight before network requests. The preflight fails with an explicit network-enabled-execution message when DNS is unavailable.

After network-enabled resume, detail validation accepted 26 of 69 archive candidates before the portal rate-limit circuit paused the run. Six HTTP 429 responses were recorded. The document pilot captured 96 files, with 13 permanent failures and 50,183 pending jobs after the 100-request batch. One response hash was shared by two URLs.
- The JSON continuation batch is a zero-yield network-outage result. Its failures remain separate from source-coverage conclusions.
