from __future__ import annotations

import json
from pathlib import Path

from .paths import WORKING_ROOT, RAW_ROOT, ensure_data_dirs
from .provenance import source_hash, write_run_manifest
from .retrieval import available_verticals, load_taxonomy, score_record, taxonomy_path
from .search import _records


VARIANTS = {
    "title_only": {"title"},
    "title_description": {"title", "description"},
    "title_description_category": {"title", "description", "classification"},
    "full_metadata": {"title", "description", "classification", "buyer", "documents", "supplier"},
}


def evaluate_baselines(verticals: list[str] | None = None) -> dict:
    ensure_data_dirs()
    source_sha = source_hash(RAW_ROOT / "ocds_full.jsonl.gz", RAW_ROOT / "manifest.json")
    records = _records()
    verticals = verticals or ["ict"]
    unknown = sorted(set(verticals) - set(available_verticals()))
    if unknown:
        raise ValueError(f"Unknown verticals: {', '.join(unknown)}")
    results: dict[str, dict] = {}
    for vertical in verticals:
        taxonomy = load_taxonomy(taxonomy_path(vertical))
        vertical_results: dict[str, dict] = {"taxonomy_version": taxonomy["version"]}
        candidate_ids: dict[str, set[str]] = {}
        for variant, fields in VARIANTS.items():
            included = []
            for record in records:
                reduced = {"id": record["id"], **{field: record.get(field) for field in fields}}
                scored = score_record(reduced, taxonomy)
                if scored["decision"] == "include":
                    included.append((record, scored))
            ids = {record["id"] for record, _ in included}
            candidate_ids[variant] = ids
            vertical_results[variant] = {
                "candidate_count": len(included),
                "unique_buyers": len({(record.get("buyer") or {}).get("id") for record, _ in included}),
                "unique_suppliers": len({supplier.get("supplier_id") for record, _ in included for supplier in record.get("supplier", [])}),
                "evidence_complete_count": sum(bool(record.get("evidence")) for record, _ in included),
            }
        full = candidate_ids["full_metadata"]
        vertical_results["overlap_with_full_metadata"] = {
            variant: len(ids & full) for variant, ids in candidate_ids.items() if variant != "full_metadata"
        }
        results[vertical] = vertical_results
    run, run_manifest_path = write_run_manifest("evaluate", source_sha, {"evaluation_version": "retrieval-baselines.2", "verticals": verticals, "results": results})
    output = {"run_id": run, "run_manifest": str(run_manifest_path), "source_snapshot_sha256": source_sha, "evaluation_version": "retrieval-baselines.2", "verticals": verticals, "results": results}
    path = WORKING_ROOT / "runs" / run / "retrieval_baseline_comparison.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    output["output"] = str(path)
    (WORKING_ROOT / "retrieval_baseline_comparison.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output
