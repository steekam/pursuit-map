from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths, ensure_data_dirs
from .provenance import source_hash, utc_now, write_run_manifest
from .raw_profile import profile_raw
from .verification import verify_outputs
from .enrichment import enrich


def _scalar(connection: duckdb.DuckDBPyConnection, query: str):
    return connection.execute(query).fetchone()[0]


def create_report(country: str = "za") -> dict:
    ensure_data_dirs(country)
    roots = country_paths(country)
    if not (roots.working / "normalization_manifest.json").exists():
        return create_raw_report(country)
    parquet_root = canonical_root(country)
    connection = duckdb.connect()
    tables = {
        "releases": "releases",
        "buyers": "buyers",
        "suppliers": "suppliers",
        "procurement_plans": "procurement_plans",
        "procurement_plan_items": "procurement_plan_items",
        "tenders": "tenders",
        "awards": "awards",
        "contracts": "contracts",
        "documents": "documents",
        "identity_audit": "identity_audit",
    }
    counts = {
        name: _scalar(connection, f"SELECT count(*) FROM read_parquet('{parquet_root / name}.parquet')")
        for name in tables
    }
    date_ranges = {}
    for table, column in (("tenders", "release_date"), ("awards", "release_date"), ("contracts", "release_date"), ("procurement_plans", "release_date"), ("procurement_plan_items", "release_date")):
        path = parquet_root / f"{table}.parquet"
        date_ranges[table] = {
            "min": _scalar(connection, f"SELECT min(try_cast(\"{column}\" AS TIMESTAMP)) FROM read_parquet('{path}')"),
            "max": _scalar(connection, f"SELECT max(try_cast(\"{column}\" AS TIMESTAMP)) FROM read_parquet('{path}')"),
        }
    stage_dates = {}
    for table, column in (("tenders", "period_start"), ("awards", "date"), ("contracts", "date_signed"), ("procurement_plans", "period_start"), ("procurement_plan_items", "period_start")):
        path = parquet_root / f"{table}.parquet"
        stage_dates[table] = {
            "min": _scalar(connection, f"SELECT min(try_cast(\"{column}\" AS TIMESTAMP)) FROM read_parquet('{path}')"),
            "max": _scalar(connection, f"SELECT max(try_cast(\"{column}\" AS TIMESTAMP)) FROM read_parquet('{path}')"),
        }
    missingness = {}
    for table, columns in {
        "buyers": ["buyer_id", "name"],
        "suppliers": ["supplier_id", "name"],
        "tenders": ["title", "description", "period_start", "value_amount"],
        "awards": ["date", "value_amount"],
        "contracts": ["date_signed", "period_start", "value_amount"],
        "procurement_plans": ["rationale", "budget_amount", "period_start"],
        "procurement_plan_items": ["description", "classification_id", "period_start", "value_amount"],
    }.items():
        path = parquet_root / f"{table}.parquet"
        missingness[table] = {
            column: _scalar(connection, f"SELECT count(*) FILTER (WHERE \"{column}\" IS NULL OR trim(cast(\"{column}\" AS VARCHAR)) = '') FROM read_parquet('{path}')")
            for column in columns
        }
    anomalies = {
        "negative_value_rows": _scalar(connection, f"""
            SELECT count(*) FROM (
            SELECT value_amount FROM read_parquet('{parquet_root / 'awards'}.parquet')
            UNION ALL SELECT value_amount FROM read_parquet('{parquet_root / 'contracts'}.parquet')
            UNION ALL SELECT value_amount FROM read_parquet('{parquet_root / 'tenders'}.parquet')
            ) WHERE value_amount < 0
        """),
        "award_supplier_orphans": _scalar(connection, f"""
            SELECT count(*) FROM read_parquet('{parquet_root / 'award_suppliers'}.parquet') s
            LEFT JOIN read_parquet('{parquet_root / 'awards'}.parquet') a
              ON s.ocid = a.ocid AND s.release_id = a.release_id AND s.award_id = a.award_id
            WHERE a.award_id IS NULL
        """),
        "duplicate_tender_release_keys": _scalar(connection, f"""
            SELECT count(*) - count(DISTINCT ocid || '|' || release_id)
            FROM read_parquet('{parquet_root / 'tenders'}.parquet')
        """),
        "supplier_id_zero_rows": _scalar(connection, f"""
            SELECT count(*) FILTER (WHERE supplier_id = '0')
            FROM read_parquet('{parquet_root / 'award_suppliers'}.parquet')
        """),
    }
    category_coverage = {
        "tender_main_procurement_category_non_null": _scalar(connection, f"""
            SELECT count(*) FILTER (WHERE main_procurement_category IS NOT NULL AND trim(main_procurement_category) <> '')
            FROM read_parquet('{parquet_root / 'tenders'}.parquet')
        """),
        "tender_main_procurement_category_distinct": _scalar(connection, f"""
            SELECT count(DISTINCT nullif(trim(main_procurement_category), ''))
            FROM read_parquet('{parquet_root / 'tenders'}.parquet')
        """),
        "plan_item_classification_non_null": _scalar(connection, f"""
            SELECT count(*) FILTER (WHERE classification_id IS NOT NULL AND trim(classification_id) <> '')
            FROM read_parquet('{parquet_root / 'procurement_plan_items'}.parquet')
        """),
        "document_url_non_null": _scalar(connection, f"""
            SELECT count(*) FILTER (WHERE url IS NOT NULL AND trim(url) <> '')
            FROM read_parquet('{parquet_root / 'documents'}.parquet')
        """),
    }
    top_categories = [
        {"category": row[0], "tender_count": row[1]}
        for row in connection.execute(f"""
            SELECT nullif(trim(main_procurement_category), '') AS category, count(*) AS tender_count
            FROM read_parquet('{parquet_root / 'tenders'}.parquet')
            WHERE nullif(trim(main_procurement_category), '') IS NOT NULL
            GROUP BY 1 ORDER BY tender_count DESC, category LIMIT 10
        """).fetchall()
    ]
    top_buyers = [
        {"buyer_id": row[0], "buyer_name": row[1], "tender_count": row[2]}
        for row in connection.execute(f"""
            SELECT buyer_id, buyer_name, count(*) AS tender_count
            FROM read_parquet('{parquet_root / 'tenders'}.parquet')
            GROUP BY 1, 2 ORDER BY tender_count DESC, buyer_name LIMIT 10
        """).fetchall()
    ]
    top_suppliers = [
        {"supplier_id": row[0], "supplier_name": row[1], "award_count": row[2]}
        for row in connection.execute(f"""
            SELECT supplier_id, supplier_name, count(*) AS award_count
            FROM read_parquet('{parquet_root / 'award_suppliers'}.parquet')
            GROUP BY 1, 2 ORDER BY award_count DESC, supplier_name LIMIT 10
        """).fetchall()
    ]
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    enrichment = enrich(country)
    report = {
        "country": country,
        "profile_mode": "canonical_parquet",
        "generated_at": utc_now(),
        "source_snapshot_sha256": source_sha,
        "counts": counts,
        "release_date_ranges": date_ranges,
        "stage_date_ranges": stage_dates,
        "missingness_null_or_blank_counts": missingness,
        "category_and_document_coverage": category_coverage,
        "top_tender_categories": top_categories,
        "top_buyers_by_tender_count": top_buyers,
        "top_suppliers_by_award_count": top_suppliers,
        "anomalies": anomalies,
        "enrichment": {
            "rule_version": enrichment["rule_version"],
            "run_id": enrichment["enrichment_run_id"],
            "row_count": enrichment["row_count"],
            "flag_counts": enrichment["flag_counts"],
            "output_root": enrichment["output_root"],
        },
        "verification": verify_outputs(country, parquet_root),
        "measured_from": "normalized Parquet tables",
        "assumptions": [
            "A compiled OCDS line is treated as one source release when it has no nested releases array.",
            "Buyer and supplier rows retain source identifiers; no cross-record entity merging is attempted.",
            "Stage date ranges are not a substitute for full release date coverage.",
        ],
        "limitations": [
            "The publisher states that coverage is incomplete because entities share data voluntarily.",
            "The source registry reports missing parties and empty/invalid fields in some records.",
            "This first report does not infer procurement need, seller fit, or causal relationships.",
        ],
    }
    run, run_manifest_path = write_run_manifest("profile", source_sha, {"country": country, "report": report, "parquet_root": str(parquet_root)}, working_root=roots.working)
    report["run_id"] = run
    report["run_manifest"] = str(run_manifest_path)
    versioned_json = roots.working / "runs" / run / "data_quality_report.json"
    versioned_markdown = roots.working / "runs" / run / "data_quality_report.md"
    report["outputs"] = {"json": str(versioned_json), "markdown": str(versioned_markdown)}
    versioned_json.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    versioned_markdown.write_text(render_markdown(report), encoding="utf-8")
    (roots.working / "data_quality_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (roots.working / "data_quality_report.md").write_text(render_markdown(report), encoding="utf-8")
    connection.close()
    return report


def create_raw_report(country: str) -> dict:
    roots = country_paths(country)
    source_path = roots.raw / "ocds_full.jsonl.gz"
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}. Run `pursuitmap ingest {country}` first.")
    source_sha = source_hash(source_path, roots.raw / "manifest.json")
    report = {
        "country": country,
        "generated_at": utc_now(),
        "source_snapshot_sha256": source_sha,
        "profile_mode": "raw_source",
        **profile_raw(source_path),
    }
    run, run_manifest_path = write_run_manifest("profile", source_sha, {"country": country, "profile_mode": "raw_source", "report": report}, working_root=roots.working)
    report["run_id"] = run
    report["run_manifest"] = str(run_manifest_path)
    versioned_json = roots.working / "runs" / run / "data_quality_report.json"
    versioned_markdown = roots.working / "runs" / run / "data_quality_report.md"
    report["outputs"] = {"json": str(versioned_json), "markdown": str(versioned_markdown)}
    versioned_json.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    versioned_markdown.write_text(render_markdown(report), encoding="utf-8")
    (roots.working / "data_quality_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (roots.working / "data_quality_report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict) -> str:
    def display(value: object) -> str:
        if value is None:
            return "—"
        if isinstance(value, (int, float)):
            return f"{value:,}"
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        return str(value)

    lines = [
        f"# {report.get('country', '').upper()} OCDS — data-quality report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Measured counts",
        "",
        "| Table | Rows |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{name}` | {count:,} |" for name, count in report["counts"].items())
    lines.extend(["", "## Release date coverage", "", "| Table | Minimum | Maximum |", "| --- | --- | --- |"])
    lines.extend(
        f"| `{stage}` | {values['min'] or '—'} | {values['max'] or '—'} |"
        for stage, values in report["release_date_ranges"].items()
    )
    lines.extend(["", "## Lifecycle field date coverage", "", "| Table | Minimum | Maximum |", "| --- | --- | --- |"])
    lines.extend(
        f"| `{stage}` | {values['min'] or '—'} | {values['max'] or '—'} |"
        for stage, values in report["stage_date_ranges"].items()
    )
    lines.extend(["", "## Missingness", "", "Counts below include NULL and blank strings.", ""])
    for table, values in report["missingness_null_or_blank_counts"].items():
        lines.append(f"- `{table}`: " + ", ".join(f"{column}={count:,}" for column, count in values.items()))
    lines.extend(["", "## Anomalies", ""])
    lines.extend(f"- `{name}`: {display(value)}" for name, value in report["anomalies"].items())
    if "enrichment" in report:
        lines.extend(["", "## Source-preserving quality flags", "", f"Rule version: `{report['enrichment']['rule_version']}`", f"Flag rows: {report['enrichment']['row_count']:,}", ""])
        lines.extend(f"- `{name}`: {display(value)}" for name, value in report["enrichment"]["flag_counts"].items())
    lines.extend(["", "## Category and document coverage", ""])
    lines.extend(f"- `{name}`: {display(value)}" for name, value in report["category_and_document_coverage"].items())
    lines.extend(["", "## Top source categories", "", "| Category | Tenders |", "| --- | ---: |"])
    lines.extend(f"| {row['category']} | {row['tender_count']:,} |" for row in report["top_tender_categories"])
    lines.extend(["", "## Top buyers by tender rows", "", "| Buyer | Tenders |", "| --- | ---: |"])
    lines.extend(f"| {row['buyer_name'] or row['buyer_id'] or '—'} | {row['tender_count']:,} |" for row in report["top_buyers_by_tender_count"])
    lines.extend(["", "## Top suppliers by award rows", "", "| Supplier | Awards |", "| --- | ---: |"])
    lines.extend(f"| {row['supplier_name'] or row['supplier_id'] or '—'} | {row['award_count']:,} |" for row in report["top_suppliers_by_award_count"])
    lines.extend(["", "## Verification", "", f"Overall status: `{report['verification']['status']}`", ""])
    lines.extend(f"- `{check['name']}`: `{check['status']}` ({check['value']})" for check in report["verification"]["checks"])
    lines.extend(["", "## Assumptions", ""])
    lines.extend(f"- {value}" for value in report["assumptions"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {value}" for value in report["limitations"])
    lines.append("")
    return "\n".join(lines)
