# ADR-002 — auditable deterministic pipeline contract

## Decision

Every transformation writes a run manifest and preserves raw source references. Canonical tables retain source IDs and raw JSON. Derived outputs carry snapshot and query/rule versions. Phase 1–1.5 intelligence uses deterministic lexical rules only.

Canonical and materialized outputs are physically stored in run-specific directories. A latest-run manifest is only a pointer; it does not overwrite prior outputs. Consumers may select a canonical normalization run explicitly with its run ID.

## Why

The source has strong text, timing, document metadata, and relationship primitives but weak planning semantics and inconsistent identifiers. Provenance and explicit quality flags prevent missing data, zero values, and placeholders from being mistaken for negative evidence.

## Consequences

- A result can be regenerated from a hashed raw snapshot.
- Prior canonical and derived outputs remain available for comparison and audit.
- Rule scores remain inspectable and comparable with simpler baselines.
- Entity resolution, document acquisition, and learned ranking remain separate decisions.
- Source changes produce measured drift rather than silent replacement.
