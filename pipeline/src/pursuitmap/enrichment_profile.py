from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths
from .provenance import sha256_file


PROFILE_VERSION = "kenya-enrichment-profile-1"
PROFILE_FIELDS = (
    "tender_number", "title", "procuring_entity_name", "procuring_entity_pin",
    "procurement_method", "procurement_category", "published_date_raw",
    "close_date_raw", "financial_year", "attachments_json",
)


def _nonempty(column: str) -> str:
    return f"count(*) FILTER (WHERE {column} IS NOT NULL AND trim(cast({column} AS VARCHAR)) <> '')"


def _render(profile: dict) -> str:
    lines = [
        "# Kenya enrichment interim profile",
        "",
        f"Run: `{profile['run_id']}`",
        f"Profile version: `{profile['profile_version']}`",
        f"Materialization SHA-256: `{profile['materialization_sha256']}`",
        "",
        "## Coverage",
        "",
        f"- Enriched rows: {profile['enriched_rows']}",
        f"- Unique enriched OCIDs: {profile['unique_enriched_ocids']}",
        f"- Canonical OCIDs: {profile['canonical_ocids']}",
        f"- Canonical coverage: {profile['canonical_coverage']:.3%}",
        "",
        "## Eligibility states",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in profile["eligibility_states"].items())
    lines.extend(["", f"Materialization consistency: `{profile['materialization_consistency']['status']}`"])
    lines.extend(["", "## Enriched field coverage", ""])
    lines.extend(f"- `{key}`: {value['present']}/{profile['enriched_rows']} ({value['coverage']:.3%})" for key, value in profile["field_coverage"].items())
    lines.extend(["", "This is an interim descriptive profile. It is regenerated from the same run directory as new materialized rows arrive."])
    return "\n".join(lines) + "\n"


def profile(run: str, *, country: str = "ke") -> dict:
    roots = country_paths(country)
    output_root = roots.enriched / run
    enriched_path = output_root / "source_enrichment.parquet"
    eligibility_path = output_root / "enrichment_eligibility.parquet"
    if not enriched_path.exists() or not eligibility_path.exists():
        raise FileNotFoundError(f"Materialized enrichment outputs are incomplete: {output_root}")
    materialization_sha = sha256_file(enriched_path)
    eligibility_sha = sha256_file(eligibility_path)
    output_path = output_root / "source_enrichment_interim_profile.json"
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if existing.get("materialization_sha256") == materialization_sha and existing.get("eligibility_sha256") == eligibility_sha:
            return existing

    canonical = canonical_root(country)
    connection = duckdb.connect()
    enriched_rows = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(enriched_path)]).fetchone()[0]
    unique_enriched_ocids = connection.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(enriched_path)]).fetchone()[0]
    canonical_ocids = connection.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(canonical / "releases.parquet")]).fetchone()[0]
    field_rows = connection.execute(
        "SELECT " + ",".join(_nonempty(column) for column in PROFILE_FIELDS) + " FROM read_parquet(?)",
        [str(enriched_path)],
    ).fetchone()
    source_snapshot = connection.execute("SELECT max(source_snapshot_sha256) FROM read_parquet(?)", [str(enriched_path)]).fetchone()[0]
    states = connection.execute("SELECT state, count(*) FROM read_parquet(?) GROUP BY state ORDER BY state", [str(eligibility_path)]).fetchall()
    connection.close()
    field_coverage = {
        column: {"present": value, "coverage": value / enriched_rows if enriched_rows else 0}
        for column, value in zip(PROFILE_FIELDS, field_rows)
    }
    eligibility_states = {str(state): count for state, count in states}
    validated_rows = eligibility_states.get("validated_detail", 0)
    profile_value = {
        "run_id": run,
        "country": country,
        "profile_version": PROFILE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "materialization_path": str(enriched_path),
        "materialization_sha256": materialization_sha,
        "eligibility_path": str(eligibility_path),
        "eligibility_sha256": eligibility_sha,
        "canonical_root": str(canonical),
        "source_snapshot_sha256": source_snapshot,
        "enriched_rows": enriched_rows,
        "unique_enriched_ocids": unique_enriched_ocids,
        "canonical_ocids": canonical_ocids,
        "canonical_coverage": unique_enriched_ocids / canonical_ocids if canonical_ocids else 0,
        "eligibility_states": eligibility_states,
        "materialization_consistency": {
            "status": "consistent" if validated_rows == enriched_rows else "lagging_eligibility",
            "enriched_rows": enriched_rows,
            "validated_detail_rows": validated_rows,
            "difference": enriched_rows - validated_rows,
        },
        "field_coverage": field_coverage,
        "limitations": [
            "Coverage is measured against the current canonical snapshot.",
            "This profile does not classify unmapped records as dead.",
            "The profile is interim while the durable enrichment run is active.",
        ],
    }
    output_path.write_text(json.dumps(profile_value, indent=2) + "\n", encoding="utf-8")
    (output_root / "source_enrichment_interim_profile.md").write_text(_render(profile_value), encoding="utf-8")
    return profile_value
