# Kenya enrichment analysis

Date: 2026-08-24

## Run

Run: `source-enrich-20260824T134223819613Z-5501335abfb5`

The run uses the Kenya OCP snapshot hash `5501335abfb5dc1dacb90bbc156c4a97e45bc59c5e4c499c845ca748ad025b97`. The detail layer contains 13,599 unique OCIDs. One closed-list page timed out after six attempts. No detail job remains pending or retryable.

## Measured quality

- Canonical OCIDs: 259,132.
- Validated PPIP detail OCIDs: 13,599.
- Canonical coverage: 5.25%.
- Mapping-pending canonical records: 245,533.
- PPIP-only mappings: 1,704.
- Tender number, title, buyer name, method, category, dates, financial year, and attachment metadata: 100% of validated rows.
- Procuring-entity PIN: 5,373/13,599 (39.51%).
- Materialization consistency: passed.

## Interpretation

The PPIP detail endpoint supplies complete metadata for the mapped cohort. The main limitation is mapping coverage. The current list API does not expose a verified PPIP ID for most canonical records. These records remain `mapping_pending`; the state does not mark them as dead.

Document acquisition remains deferred. Further API mapping investigation should precede broader document capture.
