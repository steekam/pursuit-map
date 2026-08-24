from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .enrichment_profile import PROFILE_FIELDS
from .paths import canonical_root, country_paths
from .provenance import sha256_file


ANALYSIS_VERSION = "kenya-enrichment-analysis-1"
CANONICAL_FIELDS = (
    "title", "description", "procurement_method", "category",
    "period_start", "period_end", "value_amount", "value_currency",
)


def _coverage(connection, path: Path, fields: tuple[str, ...]) -> dict:
    values = connection.execute(
        "SELECT " + ",".join(f"count(*) FILTER (WHERE {field} IS NOT NULL AND trim(cast({field} AS VARCHAR)) <> '')" for field in fields) + " FROM read_parquet(?)",
        [str(path)],
    ).fetchone()
    total = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    return {field: {"present": value, "denominator": total, "coverage": value / total if total else 0} for field, value in zip(fields, values)}


def _write_report(root: Path, stem: str, value: dict, lines: list[str]) -> None:
    (root / f"{stem}.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    (root / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(run: str, *, country: str = "ke") -> dict:
    roots = country_paths(country)
    output_root = roots.enriched / run
    enriched = output_root / "source_enrichment.parquet"
    eligibility = output_root / "enrichment_eligibility.parquet"
    if not enriched.exists() or not eligibility.exists():
        raise FileNotFoundError(f"Materialized enrichment outputs are incomplete: {output_root}")
    canonical = canonical_root(country)
    connection = duckdb.connect()
    canonical_releases = canonical / "releases.parquet"
    canonical_tenders = canonical / "tenders.parquet"
    enriched_rows = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(enriched)]).fetchone()[0]
    canonical_ocids = connection.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(canonical_releases)]).fetchone()[0]
    enriched_ocids = connection.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(enriched)]).fetchone()[0]
    source_snapshot = connection.execute("SELECT max(source_snapshot_sha256) FROM read_parquet(?)", [str(enriched)]).fetchone()[0]
    states = {str(state): count for state, count in connection.execute("SELECT state,count(*) FROM read_parquet(?) GROUP BY state ORDER BY state", [str(eligibility)]).fetchall()}
    field_coverage = {"canonical": _coverage(connection, canonical_tenders, CANONICAL_FIELDS), "ppip": _coverage(connection, enriched, PROFILE_FIELDS)}
    release_months = connection.execute("""
        WITH canonical AS (
            SELECT ocid, min(release_date) AS release_date
            FROM read_parquet(?) WHERE ocid IS NOT NULL GROUP BY ocid
        )
        SELECT coalesce(strftime(try_cast(c.release_date AS DATE), '%Y-%m'), 'unknown') AS release_month,
               count(*) FILTER (WHERE e.state = 'mapping_pending') AS mapping_pending,
               count(*) FILTER (WHERE e.state = 'validated_detail') AS validated_detail,
               count(*) FILTER (WHERE e.state = 'source_only') AS source_only,
               count(*) AS canonical_records
        FROM canonical c LEFT JOIN read_parquet(?) e ON e.ocid = c.ocid
        GROUP BY 1 ORDER BY 1
    """, [str(canonical_releases), str(eligibility)]).fetchall()
    connection.close()
    generated_at = datetime.now(UTC).isoformat()
    common = {
        "run_id": run,
        "country": country,
        "analysis_version": ANALYSIS_VERSION,
        "generated_at": generated_at,
        "source_snapshot_sha256": source_snapshot,
        "canonical_root": str(canonical),
        "input_checksums": {
            "source_enrichment.parquet": sha256_file(enriched),
            "enrichment_eligibility.parquet": sha256_file(eligibility),
            "releases.parquet": sha256_file(canonical_releases),
            "tenders.parquet": sha256_file(canonical_tenders),
        },
    }
    quality = {
        **common,
        "enriched_rows": enriched_rows,
        "unique_enriched_ocids": enriched_ocids,
        "canonical_ocids": canonical_ocids,
        "canonical_coverage": enriched_ocids / canonical_ocids if canonical_ocids else 0,
        "eligibility_states": states,
        "field_coverage": field_coverage,
        "limitations": [
            "Canonical and PPIP fields use source-specific schemas and are compared as field coverage, not as semantic equivalence.",
            "Mapping-pending records are source-coverage gaps. They are not dead records.",
            "No prediction, supplier-quality, or commercial-eligibility claim is made.",
        ],
    }
    quality_lines = [
        "# Kenya enrichment quality comparison", "", f"Run: `{run}`", "", "## Counts", "",
        f"- PPIP validated detail rows: {enriched_rows}", f"- Unique enriched OCIDs: {enriched_ocids}", f"- Canonical OCIDs: {canonical_ocids}", f"- Canonical coverage: {quality['canonical_coverage']:.3%}", "", "## Eligibility states", "",
    ]
    quality_lines.extend(f"- `{key}`: {value}" for key, value in states.items())
    quality_lines.extend(["", "## Field coverage", ""])
    for source, fields in field_coverage.items():
        quality_lines.append(f"### {source}")
        quality_lines.extend(f"- `{key}`: {value['present']}/{value['denominator']} ({value['coverage']:.3%})" for key, value in fields.items())
    _write_report(output_root, "source_enrichment_quality_report", quality, quality_lines)
    gaps = {**common, "canonical_ocids": canonical_ocids, "states": states, "release_months": [{"release_month": row[0], "mapping_pending": row[1], "validated_detail": row[2], "source_only": row[3], "canonical_records": row[4]} for row in release_months], "limitations": quality["limitations"]}
    gap_lines = ["# Kenya source mapping-gap report", "", f"Run: `{run}`", "", "## State counts", ""]
    gap_lines.extend(f"- `{key}`: {value}" for key, value in states.items())
    gap_lines.extend(["", "## Release-month mapping coverage", "", "| Release month | Canonical | Validated detail | Mapping pending | Source only |", "| --- | ---: | ---: | ---: | ---: |"])
    gap_lines.extend(f"| {row[0]} | {row[4]} | {row[2]} | {row[1]} | {row[3]} |" for row in release_months)
    _write_report(output_root, "source_mapping_gap_report", gaps, gap_lines)
    return {"run_id": run, "quality_report": str(output_root / "source_enrichment_quality_report.json"), "mapping_gap_report": str(output_root / "source_mapping_gap_report.json"), "enriched_rows": enriched_rows, "canonical_coverage": quality["canonical_coverage"], "eligibility_states": states}
