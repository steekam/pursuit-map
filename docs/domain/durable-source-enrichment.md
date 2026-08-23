# Durable source enrichment

Kenya PPIP enrichment uses a DuckDB request ledger and immutable response files.

List responses establish the mapping between PPIP internal IDs and OCDS OCIDs. Detail requests use only verified mappings. A successful detail row requires HTTP 200, valid JSON, an OCID equal to the expected OCID, a stored raw response, and a response checksum.

The engine resumes from `request_jobs`. Leases, attempts, retry state, response hashes, and failed requests remain in the ledger. A rerun over the same captured response files produces the same logical enrichment rows.

Live portal runs remain time-dependent. Reports record rate limits, retries, response status, mapping coverage, and unmatched canonical records.
