from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from .paths import RAW_ROOT, WORKING_ROOT, canonical_root
from .provenance import source_hash, write_run_manifest
from .retrieval import score_record, taxonomy_path as vertical_taxonomy_path


TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(value: object) -> list[str]:
    return TOKEN_RE.findall(str(value or "").lower())


def _records(parquet_root: Path | None = None) -> list[dict[str, Any]]:
    parquet_root = parquet_root or canonical_root()
    connection = duckdb.connect()
    rows = connection.execute(f"""
        SELECT source_snapshot_sha256, ocid, release_id, release_date, buyer_id, buyer_name,
               tender_id, title, description, category, main_procurement_category,
               additional_categories_json, procuring_entity_id, procuring_entity_name,
               procurement_method, procurement_method_details
        FROM read_parquet('{parquet_root / 'tenders'}.parquet')
    """).fetchall()
    documents = connection.execute(f"""
        SELECT ocid, release_id, document_id, document_type, title, url
        FROM read_parquet('{parquet_root / 'documents'}.parquet')
        WHERE lifecycle_type = 'tender'
    """).fetchall()
    awards = connection.execute(f"""
        SELECT a.ocid, a.release_id, s.supplier_id, s.supplier_name
        FROM read_parquet('{parquet_root / 'awards'}.parquet') a
        JOIN read_parquet('{parquet_root / 'award_suppliers'}.parquet') s
          USING (ocid, release_id, release_date, award_id)
    """).fetchall()
    connection.close()
    docs_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ocid, release_id, document_id, document_type, title, url in documents:
        docs_by_key[(ocid, release_id)].append({"document_id": document_id, "document_type": document_type, "title": title, "url": url})
    suppliers_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ocid, release_id, supplier_id, supplier_name in awards:
        suppliers_by_key[(ocid, release_id)].append({"supplier_id": supplier_id, "supplier_name": supplier_name})
    records = []
    for row in rows:
        source_sha, ocid, release_id, release_date, buyer_id, buyer_name, tender_id, title, description, category, main_category, additional, procuring_id, procuring_name, method, method_details = row
        docs = docs_by_key[(ocid, release_id)]
        suppliers = suppliers_by_key[(ocid, release_id)]
        records.append({
            "id": f"{ocid}:{release_id}:{tender_id}",
            "title": title,
            "description": description,
            "classification": {"category": category, "main": main_category, "additional": additional},
            "buyer": {"id": buyer_id, "name": buyer_name},
            "supplier": suppliers,
            "documents": [doc["title"] for doc in docs],
            "metadata": {"source_snapshot_sha256": source_sha, "ocid": ocid, "release_id": release_id, "release_date": release_date, "procuring_entity_id": procuring_id, "procuring_entity_name": procuring_name, "procurement_method": method, "procurement_method_details": method_details},
            "evidence": [{"source_type": "tender", "ocid": ocid, "release_id": release_id, "source_field_path": "tender.title", "value": title}, {"source_type": "tender", "ocid": ocid, "release_id": release_id, "source_field_path": "tender.description", "value": description}] + [{"source_type": "document_metadata", "ocid": ocid, "release_id": release_id, "document_id": doc["document_id"], "source_field_path": "tender.documents[]", "title": doc["title"], "url": doc["url"]} for doc in docs],
        })
    return records


def search(query: str, *, vertical: str = "ict", limit: int = 20, taxonomy_path: str | Path | None = None, as_of: str | None = None) -> dict[str, Any]:
    source_sha = source_hash(RAW_ROOT / "ocds_full.jsonl.gz", RAW_ROOT / "manifest.json")
    parquet_root = canonical_root()
    resolved_taxonomy_path = Path(taxonomy_path) if taxonomy_path else vertical_taxonomy_path(vertical)
    if as_of:
        as_of_manifest = WORKING_ROOT / "runs" / as_of / "run_manifest.json"
        if not as_of_manifest.exists():
            raise FileNotFoundError(f"Unknown run ID: {as_of}")
        as_of_payload = json.loads(as_of_manifest.read_text(encoding="utf-8"))
        if as_of_payload.get("source_snapshot_sha256") != source_sha:
            raise ValueError("The requested run uses a different source snapshot than the current canonical tables")
        if as_of_payload.get("operation") == "normalize":
            parquet_root = canonical_root(as_of)
    query_tokens = _tokens(query)
    candidates = []
    for record in _records(parquet_root):
        text_fields = {
            "title": str(record.get("title") or ""),
            "description": str(record.get("description") or ""),
            "classification": json.dumps(record.get("classification") or {}),
            "buyer.name": str((record.get("buyer") or {}).get("name") or ""),
            "documents": " ".join(record.get("documents") or []),
        }
        query_matches = [term for term in query_tokens if any(term in _tokens(value) for value in text_fields.values())]
        if query_tokens and not query_matches:
            continue
        scored = score_record(record, taxonomy_path=resolved_taxonomy_path)
        if scored["decision"] != "include":
            continue
        query_breakdown = []
        for field, value in text_fields.items():
            field_tokens = _tokens(value)
            for term in query_tokens:
                count = field_tokens.count(term)
                if count:
                    query_breakdown.append({"field": field, "term": term, "count": count, "score": count})
        result = {
            **scored,
            "query": query,
            "query_terms": query_tokens,
            "query_matches": query_matches,
            "query_score": float(sum(item["score"] for item in query_breakdown)),
            "score": float(scored["best_score"]) + float(sum(item["score"] for item in query_breakdown)),
            "score_breakdown": {"query": query_breakdown, "vertical": scored["best_category"]["score_breakdown"] if scored["best_category"] else []},
            "metadata": record["metadata"],
            "evidence": record["evidence"],
            "supplier_context": record["supplier"],
        }
        candidates.append(result)
    candidates.sort(key=lambda item: (-item["score"], str(item["metadata"].get("ocid") or ""), str(item["metadata"].get("release_id") or "")))
    candidates = candidates[:limit]
    run, run_manifest_path = write_run_manifest("search", source_sha, {"query": query, "vertical": vertical, "limit": limit, "result_count": len(candidates), "taxonomy_path": str(resolved_taxonomy_path)})
    return {"run_id": run, "run_manifest": str(run_manifest_path), "as_of": as_of, "source_snapshot_sha256": source_sha, "query": query, "vertical": vertical, "limit": limit, "result_count": len(candidates), "results": candidates}
