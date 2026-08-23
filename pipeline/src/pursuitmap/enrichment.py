from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths, ensure_data_dirs
from .provenance import parquet_checksums, run_id, source_hash, utc_now, write_run_manifest


QUALITY_FLAG_COLUMNS = [
    "source_snapshot_sha256", "country", "ocid", "release_id", "table_name",
    "source_record_key", "source_field_path", "flag_code", "flag_status",
    "observed_value_raw", "rule_version", "enrichment_run_id", "generated_at",
]
RULE_VERSION = "kenya-quality-1"


def _sql_text(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def _empty_flags_sql() -> str:
    columns = ", ".join(f'CAST(NULL AS VARCHAR) AS "{column}"' for column in QUALITY_FLAG_COLUMNS)
    return f"SELECT {columns} WHERE FALSE"


def enrich(country: str = "ke") -> dict:
    ensure_data_dirs(country)
    roots = country_paths(country)
    parquet_root = canonical_root(country)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    run = run_id(source_sha, "enrich")
    output_root = roots.enriched / run
    output_root.mkdir(parents=True, exist_ok=False)
    generated_at = utc_now()
    connection = duckdb.connect()
    flag_queries: list[str] = []
    if country == "ke":
        prefix = f"SELECT {_sql_text(source_sha)} AS source_snapshot_sha256, {_sql_text(country)} AS country, "
        suffix = f", {_sql_text(RULE_VERSION)} AS rule_version, {_sql_text(run)} AS enrichment_run_id, {_sql_text(generated_at)} AS generated_at"
        tenders = f"read_parquet('{parquet_root / 'tenders.parquet'}')"
        releases = f"read_parquet('{parquet_root / 'releases.parquet'}')"
        awards = f"read_parquet('{parquet_root / 'awards.parquet'}')"
        contracts = f"read_parquet('{parquet_root / 'contracts.parquet'}')"
        suppliers = f"read_parquet('{parquet_root / 'suppliers.parquet'}')"
        flag_queries.extend([
            f"{prefix}ocid, release_id, 'tenders' AS table_name, tender_id AS source_record_key, '$.tender.description' AS source_field_path, 'tender.description_missing' AS flag_code, 'observed' AS flag_status, description AS observed_value_raw{suffix} FROM {tenders} WHERE description IS NULL OR trim(description) = ''",
            f"{prefix}ocid, release_id, 'tenders', tender_id, '$.tender.value.amount', 'tender.value_missing', 'observed', value_amount_raw{suffix} FROM {tenders} WHERE value_amount IS NULL",
            f"{prefix}ocid, release_id, 'tenders', tender_id, '$.tender.tenderPeriod.startDate', 'tender.period_start_missing_or_invalid', period_start_status, period_start_raw{suffix} FROM {tenders} WHERE period_start_status <> 'valid' OR try_cast(period_start AS TIMESTAMP) < TIMESTAMP '2000-01-01' OR try_cast(period_start AS TIMESTAMP) > TIMESTAMP '2100-01-01'",
            f"{prefix}ocid, release_id, 'tenders', tender_id, '$.tender.tenderPeriod.endDate', 'tender.period_end_missing_or_invalid', period_end_status, period_end_raw{suffix} FROM {tenders} WHERE period_end_status <> 'valid' OR try_cast(period_end AS TIMESTAMP) < TIMESTAMP '2000-01-01' OR try_cast(period_end AS TIMESTAMP) > TIMESTAMP '2100-01-01'",
            f"{prefix}ocid, release_id, 'awards', award_id, '$.awards[].date', 'award.date_missing', 'observed', date_raw{suffix} FROM {awards} WHERE date IS NULL OR trim(date) = ''",
            f"{prefix}ocid, release_id, 'contracts', contract_id, '$.contracts[].dateSigned', 'contract.date_signed_missing', 'observed', date_signed_raw{suffix} FROM {contracts} WHERE date_signed IS NULL OR trim(date_signed) = ''",
            f"{prefix}ocid, release_id, 'contracts', contract_id, '$.contracts[].period.startDate', 'contract.period_start_missing_or_invalid', period_start_status, period_start_raw{suffix} FROM {contracts} WHERE period_start_status <> 'valid'",
            f"{prefix}ocid, release_id, 'contracts', contract_id, '$.contracts[].awardID', 'contract.award_reference_missing', 'observed', award_id{suffix} FROM {contracts} c WHERE award_id IS NULL OR trim(award_id) = ''",
            f"{prefix}NULL, NULL, 'releases', ocid || '|' || release_id, '$.planning', 'planning.object_absent', 'observed', NULL{suffix} FROM {releases} r WHERE NOT EXISTS (SELECT 1 FROM read_parquet('{parquet_root / 'procurement_plans.parquet'}') p WHERE p.ocid = r.ocid AND p.release_id = r.release_id)",
            f"{prefix}NULL, NULL, 'releases', ocid || '|' || release_id, '$.documents', 'documents.object_absent', 'observed', NULL{suffix} FROM {releases} r WHERE NOT EXISTS (SELECT 1 FROM read_parquet('{parquet_root / 'documents.parquet'}') d WHERE d.ocid = r.ocid AND d.release_id = r.release_id)",
            f"{prefix}NULL, NULL, 'suppliers', supplier_id, '$.suppliers[].name', 'supplier.name_missing', 'observed', name{suffix} FROM {suppliers} WHERE name IS NULL OR trim(name) = ''",
        ])
    if flag_queries:
        union = " UNION ALL ".join(flag_queries)
        connection.execute(f"CREATE TABLE quality_flags AS SELECT * FROM ({union}) flags")
    else:
        connection.execute(f"CREATE TABLE quality_flags AS {_empty_flags_sql()}")
    connection.execute(f"COPY quality_flags TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(output_root / "quality_flags.parquet")])
    columns = [row[0] for row in connection.execute("DESCRIBE quality_flags").fetchall()]
    if columns != QUALITY_FLAG_COLUMNS:
        raise ValueError(f"Quality flag schema mismatch: {columns}")
    counts = {row[0]: row[1] for row in connection.execute("SELECT flag_code, count(*) FROM quality_flags GROUP BY 1 ORDER BY 1").fetchall()}
    connection.close()
    manifest = {
        "country": country, "source_snapshot_sha256": source_sha, "rule_version": RULE_VERSION,
        "enrichment_run_id": run, "canonical_root": str(parquet_root), "output_root": str(output_root),
        "row_count": sum(counts.values()), "flag_counts": counts,
        "parquet_sha256": parquet_checksums(output_root), "generated_at": generated_at,
        "limitations": ["Flags record source availability and validity. They do not repair or infer source values."],
    }
    run, manifest_path = write_run_manifest("enrich", source_sha, manifest, run=run, working_root=roots.working)
    manifest["run_manifest"] = str(manifest_path)
    (output_root / "enrichment_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (roots.working / "enrichment_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
