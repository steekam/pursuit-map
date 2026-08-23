"""DuckDB-backed canonical normalization for large JSONL sources."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .normalize import TABLE_COLUMNS
from .paths import country_paths, ensure_data_dirs
from .provenance import parquet_checksums, run_id, source_hash, utc_now, write_run_manifest


def _type(column: str) -> str:
    if column in {"quantity", "value_amount", "budget_amount"}:
        return "DOUBLE"
    if column == "planning_present":
        return "BOOLEAN"
    return "VARCHAR"


def _empty_sql(table: str) -> str:
    columns = ", ".join(f'CAST(NULL AS {_type(column)}) AS "{column}"' for column in TABLE_COLUMNS[table])
    return f'CREATE TABLE "{table}" AS SELECT {columns} WHERE FALSE'


def _date(raw: str, prefix: str) -> str:
    return (
        f"{raw} AS {prefix}_raw, "
        f"CASE WHEN {raw} IS NULL OR {raw} = '' OR starts_with({raw}, '0001-01-01') "
        f"THEN NULL ELSE try_cast({raw} AS TIMESTAMP)::VARCHAR END AS {prefix}, "
        f"CASE WHEN {raw} IS NULL OR {raw} = '' THEN 'missing' "
        f"WHEN starts_with({raw}, '0001-01-01') THEN 'sentinel' "
        f"WHEN try_cast({raw} AS TIMESTAMP) IS NULL THEN 'invalid' ELSE 'valid' END AS {prefix}_status"
    )


def _value(obj: str, prefix: str = "value") -> str:
    raw = f"json_extract_string({obj}, '$.amount')"
    return (
        f"{raw} AS {prefix}_amount_raw, try_cast({raw} AS DOUBLE) AS {prefix}_amount, "
        f"json_extract_string({obj}, '$.currency') AS {prefix}_currency, "
        f"CASE WHEN {raw} IS NULL OR {raw} = '' THEN 'missing' "
        f"WHEN try_cast({raw} AS DOUBLE) IS NULL THEN 'invalid' "
        f"WHEN try_cast({raw} AS DOUBLE) = 0 THEN 'zero' "
        f"WHEN try_cast({raw} AS DOUBLE) < 0 THEN 'negative' ELSE 'valid' END AS {prefix}_status"
    )


def _create(connection: duckdb.DuckDBPyConnection, table: str, query: str) -> None:
    connection.execute(f'DROP TABLE IF EXISTS "{table}"')
    connection.execute(f'CREATE TABLE "{table}" AS {query}')


def normalize_vectorized(source_path: Path, *, country: str = "ke") -> dict:
    ensure_data_dirs(country)
    roots = country_paths(country)
    source_sha = source_hash(source_path, source_path.parent / "manifest.json")
    run = run_id(source_sha, "normalize-vectorized")
    parquet_root = roots.parquet / run
    parquet_root.mkdir(parents=True, exist_ok=False)
    database_path = roots.working / "runs" / run / f"{country}.duckdb"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    connection.execute(
        """CREATE TEMP TABLE source AS
        SELECT row_number() OVER () AS source_row, json::JSON AS raw_json,
               json_extract_string(json, '$.ocid') AS ocid,
               json_extract_string(json, '$.id') AS release_id,
               json_extract_string(json, '$.date') AS release_date_raw,
               CASE WHEN json_extract_string(json, '$.date') IS NULL OR starts_with(json_extract_string(json, '$.date'), '0001-01-01') THEN NULL ELSE try_cast(json_extract_string(json, '$.date') AS TIMESTAMP)::VARCHAR END AS release_date,
               json_extract_string(json, '$.buyer.id') AS buyer_id,
               json_extract_string(json, '$.buyer.name') AS buyer_name,
               json_extract_string(json, '$.publisher.name') AS publisher_name,
               json_extract_string(json, '$.language') AS language
        FROM read_json_objects(?)""",
        [str(source_path)],
    )
    src = "source"
    common = "s.source_snapshot_sha256, s.ocid, s.release_id, s.release_date, s.buyer_id, s.buyer_name"
    _create(connection, "releases", f"""
        SELECT '{source_sha}' AS source_snapshot_sha256, ocid, release_id, release_date_raw, release_date,
               CASE WHEN release_date_raw IS NULL OR release_date_raw = '' THEN 'missing' WHEN starts_with(release_date_raw, '0001-01-01') THEN 'sentinel' WHEN try_cast(release_date_raw AS TIMESTAMP) IS NULL THEN 'invalid' ELSE 'valid' END AS release_date_status,
               json_extract(raw_json, '$.tag')::VARCHAR AS tags_json, json_extract_string(raw_json, '$.initiationType') AS initiation_type, buyer_id, buyer_name, publisher_name, language, raw_json::VARCHAR AS raw_json
        FROM source""")
    _create(connection, "buyers", f"""
        SELECT DISTINCT '{source_sha}' AS source_snapshot_sha256, buyer_id, buyer_name AS name,
               regexp_replace(lower(trim(buyer_name)), '\\s+', ' ', 'g') AS normalized_name,
               CASE WHEN buyer_id IS NULL OR trim(buyer_id) = '' THEN 'missing' WHEN trim(buyer_id) IN ('0','000000','UNKNOWN','N/A') THEN 'placeholder' ELSE 'present' END AS identifier_status
        FROM source WHERE buyer_id IS NOT NULL OR buyer_name IS NOT NULL ORDER BY buyer_id, name""")
    _create(connection, "suppliers", f"""
        SELECT DISTINCT '{source_sha}' AS source_snapshot_sha256, json_extract_string(a.value, '$.id') AS supplier_id, json_extract_string(a.value, '$.name') AS name,
               regexp_replace(lower(trim(json_extract_string(a.value, '$.name'))), '\\s+', ' ', 'g') AS normalized_name,
               CASE WHEN json_extract_string(a.value, '$.id') IS NULL OR trim(json_extract_string(a.value, '$.id')) = '' THEN 'missing' WHEN trim(json_extract_string(a.value, '$.id')) IN ('0','000000','UNKNOWN','N/A') THEN 'placeholder' ELSE 'present' END AS identifier_status
        FROM source s, json_each(s.raw_json, '$.awards') aw, json_each(aw.value, '$.suppliers') a ORDER BY supplier_id, name""")
    _create(connection, "procurement_plans", f"""
        SELECT s.source_snapshot_sha256, s.ocid, s.release_id, s.release_date, TRUE AS planning_present, json_extract_string(s.raw_json, '$.planning.rationale') AS rationale, json_extract_string(s.raw_json, '$.planning.budget.description') AS budget_description,
               {_value("json_extract(s.raw_json, '$.planning.budget')", "budget")}, {_date("json_extract_string(s.raw_json, '$.planning.period.startDate')", "period_start")}, {_date("json_extract_string(s.raw_json, '$.planning.period.endDate')", "period_end")},
               json_array_length(json_extract(s.raw_json, '$.planning.items')) AS items_count, json_extract(s.raw_json, '$.planning')::VARCHAR AS raw_json
        FROM (SELECT '{source_sha}' AS source_snapshot_sha256, ocid, release_id, release_date, buyer_id, buyer_name, raw_json FROM source) s
        WHERE json_extract(s.raw_json, '$.planning') IS NOT NULL""")
    _create(connection, "tenders", f"""
        SELECT {common}, json_extract_string(s.raw_json, '$.tender.id') AS tender_id, json_extract_string(s.raw_json, '$.tender.title') AS title, json_extract_string(s.raw_json, '$.tender.description') AS description,
               json_extract_string(s.raw_json, '$.tender.status') AS status, json_extract_string(s.raw_json, '$.tender.procurementMethod') AS procurement_method, json_extract_string(s.raw_json, '$.tender.procurementMethodDetails') AS procurement_method_details,
               json_extract_string(s.raw_json, '$.tender.category') AS category, json_extract_string(s.raw_json, '$.tender.mainProcurementCategory') AS main_procurement_category, json_extract(s.raw_json, '$.tender.additionalProcurementCategories')::VARCHAR AS additional_categories_json,
               json_extract_string(s.raw_json, '$.tender.procuringEntity.id') AS procuring_entity_id, json_extract_string(s.raw_json, '$.tender.procuringEntity.name') AS procuring_entity_name,
               {_date("json_extract_string(s.raw_json, '$.tender.enquiryPeriod.startDate')", "enquiry_start")}, {_date("json_extract_string(s.raw_json, '$.tender.enquiryPeriod.endDate')", "enquiry_end")},
               {_date("json_extract_string(s.raw_json, '$.tender.tenderPeriod.startDate')", "period_start")}, {_date("json_extract_string(s.raw_json, '$.tender.tenderPeriod.endDate')", "period_end")},
               {_value("json_extract(s.raw_json, '$.tender.value')")}, json_extract(s.raw_json, '$.tender')::VARCHAR AS raw_json
        FROM (SELECT '{source_sha}' AS source_snapshot_sha256, ocid, release_id, release_date, buyer_id, buyer_name, raw_json FROM source) s
        WHERE json_extract(s.raw_json, '$.tender') IS NOT NULL""")
    _create(connection, "awards", f"""
        SELECT '{source_sha}' AS source_snapshot_sha256, s.ocid, s.release_id, s.release_date, s.buyer_id, s.buyer_name, json_extract_string(a.value, '$.id') AS award_id, json_extract_string(a.value, '$.title') AS title, json_extract_string(a.value, '$.description') AS description, json_extract_string(a.value, '$.status') AS status,
               {_date("json_extract_string(a.value, '$.date')", "date")}, {_value("json_extract(a.value, '$.value')")}, a.value::VARCHAR AS raw_json
        FROM source s, json_each(s.raw_json, '$.awards') a""")
    _create(connection, "award_suppliers", f"""
        SELECT '{source_sha}' AS source_snapshot_sha256, s.ocid, s.release_id, s.release_date, json_extract_string(a.value, '$.id') AS award_id, json_extract_string(p.value, '$.id') AS supplier_id, json_extract_string(p.value, '$.name') AS supplier_name,
               CASE WHEN json_extract_string(p.value, '$.id') IS NULL OR trim(json_extract_string(p.value, '$.id')) = '' THEN 'missing' WHEN trim(json_extract_string(p.value, '$.id')) IN ('0','000000','UNKNOWN','N/A') THEN 'placeholder' ELSE 'present' END AS identifier_status
        FROM source s, json_each(s.raw_json, '$.awards') a, json_each(a.value, '$.suppliers') p ORDER BY ocid, release_id, award_id, supplier_id""")
    _create(connection, "contracts", f"""
        SELECT '{source_sha}' AS source_snapshot_sha256, s.ocid, s.release_id, s.release_date, s.buyer_id, s.buyer_name, json_extract_string(c.value, '$.id') AS contract_id, json_extract_string(c.value, '$.awardID') AS award_id, json_extract_string(c.value, '$.title') AS title, json_extract_string(c.value, '$.description') AS description, json_extract_string(c.value, '$.status') AS status,
               {_date("json_extract_string(c.value, '$.dateSigned')", "date_signed")}, {_date("json_extract_string(c.value, '$.period.startDate')", "period_start")}, {_date("json_extract_string(c.value, '$.period.endDate')", "period_end")}, {_value("json_extract(c.value, '$.value')")}, c.value::VARCHAR AS raw_json
        FROM source s, json_each(s.raw_json, '$.contracts') c""")
    _create(connection, "documents", f"SELECT {', '.join('CAST(NULL AS '+_type(c)+') AS "'+c+'"' for c in TABLE_COLUMNS['documents'])} WHERE FALSE")
    _create(connection, "procurement_plan_items", f"SELECT {', '.join('CAST(NULL AS '+_type(c)+') AS "'+c+'"' for c in TABLE_COLUMNS['procurement_plan_items'])} WHERE FALSE")
    _create(connection, "identity_audit", f"SELECT {', '.join('CAST(NULL AS '+_type(c)+') AS "'+c+'"' for c in TABLE_COLUMNS['identity_audit'])} WHERE FALSE")

    counts: dict[str, int] = {}
    for table, columns in TABLE_COLUMNS.items():
        actual = [row[0] for row in connection.execute(f"DESCRIBE \"{table}\"").fetchall()]
        if actual != columns:
            raise ValueError(f"Schema mismatch for {table}: {actual}")
        connection.execute(f'COPY "{table}" TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(parquet_root / f"{table}.parquet")])
        counts[table] = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    connection.close()
    manifest = {"normalized_at": utc_now(), "source_path": str(source_path), "source_snapshot_sha256": source_sha, "release_count": counts["releases"], "row_counts": counts, "database": str(database_path), "parquet_root": str(parquet_root), "parquet_sha256": parquet_checksums(parquet_root), "normalization_mode": "duckdb_vectorized"}
    run, manifest_path = write_run_manifest("normalize", source_sha, manifest, run=run, working_root=roots.working)
    manifest["run_id"] = run
    manifest["run_manifest"] = str(manifest_path)
    (roots.working / "normalization_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
