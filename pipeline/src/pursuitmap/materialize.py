from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .paths import MATERIALIZED_ROOT, RAW_ROOT, WORKING_ROOT, canonical_root, ensure_data_dirs
from .provenance import source_hash, write_run_manifest
from .retrieval import load_taxonomy, score_record
from .search import _records


QUERIES = {
    "activity_monthly": """
        SELECT date_trunc('month', try_cast(release_date AS TIMESTAMP)) AS month,
               main_procurement_category AS category,
               count(*) AS tender_count,
               count(DISTINCT buyer_id) AS buyer_count
        FROM read_parquet('{root}/tenders.parquet')
        GROUP BY 1, 2 ORDER BY 1, 2
    """,
    "buyer_activity": """
        SELECT buyer_id, buyer_name,
               count(*) AS tender_count,
               count(DISTINCT ocid) AS contracting_process_count
        FROM read_parquet('{root}/tenders.parquet')
        GROUP BY 1, 2 ORDER BY tender_count DESC, buyer_name
    """,
    "supplier_activity": """
        SELECT supplier_id, supplier_name,
               count(*) AS award_count,
               count(DISTINCT ocid) AS contracting_process_count
        FROM read_parquet('{root}/award_suppliers.parquet')
        GROUP BY 1, 2 ORDER BY award_count DESC, supplier_name
    """,
    "buyer_supplier_relationships": """
        SELECT a.buyer_id, a.buyer_name, s.supplier_id, s.supplier_name,
               count(*) AS award_count,
               count(DISTINCT a.ocid) AS contracting_process_count
        FROM read_parquet('{root}/awards.parquet') a
        JOIN read_parquet('{root}/award_suppliers.parquet') s
          USING (ocid, release_id, release_date, award_id)
        GROUP BY 1, 2, 3, 4 ORDER BY award_count DESC, a.buyer_name, s.supplier_name
    """,
    "category_activity": """
        SELECT category, main_procurement_category, count(*) AS tender_count,
               count(DISTINCT buyer_id) AS buyer_count
        FROM read_parquet('{root}/tenders.parquet')
        GROUP BY 1, 2 ORDER BY tender_count DESC, category
    """,
    "contract_timing": """
        SELECT buyer_id, buyer_name, contract_id, award_id, status,
               date_signed, date_signed_status, period_start, period_start_status,
               period_end, period_end_status, value_amount, value_currency, value_status,
               ocid, release_id
        FROM read_parquet('{root}/contracts.parquet')
        ORDER BY date_signed, buyer_name, contract_id
    """,
    "document_availability": """
        SELECT lifecycle_type, document_type,
               count(*) AS document_count,
               count(*) FILTER (WHERE url IS NOT NULL AND trim(url) <> '') AS url_count
        FROM read_parquet('{root}/documents.parquet')
        GROUP BY 1, 2 ORDER BY document_count DESC, lifecycle_type, document_type
    """,
}


def materialize() -> dict:
    ensure_data_dirs()
    manifest_path = WORKING_ROOT / "normalization_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Run `pursuitmap normalize za` before materializing outputs.")
    normalization = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_sha = normalization["source_snapshot_sha256"]
    parquet_root = canonical_root(normalization["run_id"])
    run, run_manifest_path = write_run_manifest("materialize", source_sha, {"query_version": "phase1-marts.1", "source_parquet_root": str(parquet_root)})
    output_root = MATERIALIZED_ROOT / run
    output_root.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    row_counts: dict[str, int] = {}
    output_paths: dict[str, str] = {}
    for name, query in QUERIES.items():
        relation = connection.sql(f"SELECT '{source_sha}' AS source_snapshot_sha256, 'phase1-marts.1' AS query_version, * FROM ({query.format(root=parquet_root)}) AS derived")
        output_path = output_root / f"{name}.parquet"
        relation.to_parquet(str(output_path), compression="zstd")
        row_counts[name] = relation.count("*").fetchone()[0]
        output_paths[name] = str(output_path)
    taxonomy = load_taxonomy()
    ict_candidates = []
    for record in _records():
        scored = score_record(record, taxonomy)
        if scored["decision"] != "include":
            continue
        ict_candidates.append({
            "source_snapshot_sha256": source_sha,
            "query_version": "phase1-marts.1",
            "record_id": scored["record_id"],
            "metadata": scored.get("metadata", {}),
            "best_category": scored["best_category"],
            "score": scored["best_score"],
            "evidence": scored.get("evidence", []),
            "supplier_context": record.get("supplier", []),
        })
    candidate_path = output_root / "ict_candidates.json"
    candidate_path.write_text(json.dumps(ict_candidates, indent=2, default=str) + "\n", encoding="utf-8")
    row_counts["ict_candidates"] = len(ict_candidates)
    output_paths["ict_candidates"] = str(candidate_path)
    connection.close()
    result = {
        "run_id": run,
        "run_manifest": str(run_manifest_path),
        "source_snapshot_sha256": source_sha,
        "query_version": "phase1-marts.1",
        "row_counts": row_counts,
        "outputs": output_paths,
    }
    (output_root / "materialization_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (MATERIALIZED_ROOT / "phase1_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
