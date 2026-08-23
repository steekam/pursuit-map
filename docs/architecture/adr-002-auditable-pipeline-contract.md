# ADR-002 — auditable deterministic pipeline contract

## Decision

Every transformation writes a run manifest and preserves raw source references. Canonical tables retain source IDs and raw JSON. Derived outputs carry snapshot and query or rule versions. Phase 1 and Phase 1.5 use deterministic lexical rules.

Canonical and materialized outputs use run-specific directories. A latest-run manifest points to one run. It does not replace earlier outputs. Consumers can select a canonical normalization run by run ID.

## Why

The source has useful text, timing, document metadata, and relationship fields. Planning semantics are weak. Identifiers are inconsistent. Provenance and quality flags distinguish missing data, zero values, and placeholders from negative evidence.

## Consequences

- A result can be regenerated from a hashed raw snapshot.
- Earlier canonical and derived outputs remain available for comparison and audit.
- Rule scores remain inspectable and comparable with simple baselines.
- Entity resolution, document acquisition, and learned ranking remain separate decisions.
- Source changes produce measured drift. The pipeline does not silently replace earlier results.
