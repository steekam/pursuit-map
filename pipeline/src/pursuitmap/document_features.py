from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from .provenance import sha256_file, utc_now


OCCURRENCE_COLUMNS = [
    "source_snapshot_sha256", "source_run_id", "document_download_run_id", "extraction_run_id", "document_hash", "ocid", "release_id", "document_id", "source_url",
    "feature_key", "family", "value_raw", "value_normalized", "value_type", "page_number", "table_number",
    "section_heading", "docling_pointer", "bbox_json", "coordinate_origin", "table_row", "table_column", "evidence_text", "extraction_method", "ocr_derived", "ocr_status",
    "parse_status", "rule_version", "generated_at",
]
LINK_COLUMNS = ["source_snapshot_sha256", "source_run_id", "document_download_run_id", "extraction_run_id", "document_hash", "ocid", "release_id", "document_id", "source_url", "generated_at"]
SUMMARY_COLUMNS = [
    "source_snapshot_sha256", "source_run_id", "document_download_run_id", "extraction_run_id", "document_hash", "document_role", "document_title", "primary_tender_number",
    "primary_submission_deadline", "primary_opening_date", "primary_buyer_name", "primary_procurement_method",
    "primary_bid_security_amount", "primary_tender_fee", "primary_validity_period_days", "primary_framework_term",
    "primary_delivery_location", "lots_json", "specifications_json", "quantities_json", "eligibility_json",
    "evaluation_criteria_json", "ict_terms_json", "occurrence_count", "conflict_count", "ambiguity_count", "quality_status", "generated_at",
]
WIDE_FEATURES = {
    "document_role": "document_role", "document_title": "document_title", "tender_number": "primary_tender_number",
    "submission_deadline": "primary_submission_deadline", "opening_date": "primary_opening_date", "buyer_name": "primary_buyer_name",
    "procurement_method": "primary_procurement_method", "bid_security_amount": "primary_bid_security_amount", "tender_fee": "primary_tender_fee",
    "validity_period_days": "primary_validity_period_days", "framework_term": "primary_framework_term", "delivery_location": "primary_delivery_location",
}


def normalize_text(value: str) -> str:
    value = html.unescape(value or "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value).lower()).strip()


def _parse_date(value: str) -> str | None:
    raw = normalize_text(value)
    raw = re.sub(r"(\d)(?:st|nd|rd|th)", r"\1", raw, flags=re.I)
    formats = ["%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"\b(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b", raw)
    if match:
        try:
            return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        except ValueError:
            return None
    return None


def _parse_amount(value: str) -> str | None:
    match = re.search(r"(?:KES|KSH|USD|EUR|GBP|KENYA\s+SHILLINGS)?\s*([0-9][0-9,]*(?:\.\d+)?)", value, re.I)
    if not match:
        return None
    return match[1].replace(",", "")


def _normalized_value(feature_key: str, value: str, value_type: str) -> tuple[str | None, str]:
    raw = normalize_text(value)
    if value_type == "datetime":
        parsed = _parse_date(raw)
        return parsed, "valid" if parsed else "unparsed"
    if value_type == "amount":
        parsed = _parse_amount(raw)
        return parsed, "valid" if parsed else "unparsed"
    if value_type == "integer":
        match = re.search(r"\b(\d{1,4})\b", raw)
        return (match[1], "valid") if match else (None, "unparsed")
    if value_type == "number":
        match = re.search(r"\b(\d+(?:\.\d+)?)\b", raw)
        return (match[1], "valid") if match else (None, "unparsed")
    if value_type == "boolean":
        return ("true", "valid") if "mandatory" in _tokens(raw) else ("false", "valid")
    return (_tokens(raw), "valid") if raw else (None, "missing")


def _rules(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not value.get("rule_version") or not value.get("rules"):
        raise ValueError("Document rule registry requires rule_version and rules")
    defaults = value.get("rule_defaults", {})
    required = {"feature_key", "family", "value_type", "patterns"}
    for rule in value["rules"]:
        missing = required - set(rule)
        if missing:
            raise ValueError(f"Document rule is missing fields: {sorted(missing)}")
        for key, default in defaults.items():
            rule.setdefault(key, default)
    return value


def _provenance(item: dict[str, Any]) -> tuple[int | None, dict[str, Any] | None, str | None]:
    prov = item.get("prov") or []
    first = prov[0] if prov else {}
    bbox = first.get("bbox") or {}
    return first.get("page_no"), bbox, bbox.get("coord_origin")


def _units(doc: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    section = ""

    def resolve(ref: str) -> dict[str, Any] | None:
        try:
            _, collection, index = ref.split("/")
            return (doc.get(collection) or [])[int(index)]
        except (ValueError, IndexError, TypeError):
            return None

    def visit(ref: str) -> None:
        nonlocal section
        item = resolve(ref)
        if not item:
            return
        if ref.startswith("#/groups/"):
            for child in item.get("children") or []:
                if child.get("$ref"):
                    visit(child["$ref"])
            return
        if ref.startswith("#/texts/"):
            text = normalize_text(item.get("text") or item.get("orig") or "")
            if not text:
                return
            if item.get("label") == "section_header":
                section = text
            page, bbox, origin = _provenance(item)
            units.append({"text": text, "page": page, "bbox": bbox, "origin": origin, "pointer": item.get("self_ref"), "section": section, "method": "docling_text", "table": None, "row": None, "column": None})
            return
        if ref.startswith("#/tables/"):
            page, table_bbox, table_origin = _provenance(item)
            table_number = int(ref.rsplit("/", 1)[1])
            for cell in ((item.get("data") or {}).get("table_cells") or []):
                text = normalize_text(cell.get("text") or "")
                if text:
                    cell_bbox = cell.get("bbox") or table_bbox
                    units.append({"text": text, "page": page, "bbox": cell_bbox, "origin": cell_bbox.get("coord_origin") or table_origin, "pointer": f"{item.get('self_ref')}/data/table_cells", "section": section, "method": "docling_table", "table": table_number, "row": cell.get("start_row_offset_idx"), "column": cell.get("start_col_offset_idx")})

    children = ((doc.get("body") or {}).get("children") or [])
    if children:
        for child in children:
            if child.get("$ref"):
                visit(child["$ref"])
    else:
        for item in (doc.get("texts") or []) + (doc.get("tables") or []):
            if item.get("self_ref"):
                visit(item["self_ref"])
    return units


def _matches(rule: dict[str, Any], text: str) -> list[str]:
    lowered = _tokens(text)
    return [pattern for pattern in rule.get("patterns", []) if _tokens(pattern) and _tokens(pattern) in lowered]


def _value_for(rule: dict[str, Any], text: str, matches: list[str]) -> str:
    feature = rule["feature_key"]
    if feature.endswith("_term"):
        return ", ".join(matches)
    if rule["value_type"] == "boolean":
        return "true"
    for marker in matches:
        match = re.search(re.escape(marker) + r"\s*[:\-]?\s*(.{0,300})", text, re.I)
        if match and match[1].strip():
            return normalize_text(match[1])
    return text[:500]


def _occurrences(document: dict[str, Any], registry: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in _units(document):
        for rule in registry["rules"]:
            matches = _matches(rule, unit["text"])
            if not matches:
                continue
            raw = _value_for(rule, unit["text"], matches)
            normalized, parse_status = _normalized_value(rule["feature_key"], raw, rule["value_type"])
            rows.append({
                **metadata, "feature_key": rule["feature_key"], "family": rule["family"], "value_raw": raw,
                "value_normalized": normalized, "value_type": rule["value_type"], "page_number": unit["page"],
                "table_number": unit["table"], "section_heading": unit["section"], "docling_pointer": unit["pointer"],
                "bbox_json": json.dumps(unit["bbox"], sort_keys=True) if unit["bbox"] else None, "coordinate_origin": unit["origin"], "table_row": unit["row"], "table_column": unit["column"], "evidence_text": unit["text"],
                "extraction_method": unit["method"], "ocr_derived": None, "ocr_status": "unknown", "parse_status": parse_status,
                "rule_version": registry["rule_version"], "generated_at": utc_now(),
            })
    return rows


def _primary(values: list[dict[str, Any]]) -> tuple[str | None, str]:
    valid = [row for row in values if row["value_normalized"]]
    unique = {row["value_normalized"] for row in valid}
    if not valid:
        return None, "missing"
    if len(unique) == 1:
        return valid[0]["value_normalized"], "selected"
    dated = [(row["value_normalized"], row) for row in valid if row["value_type"] == "datetime" and row["value_normalized"]]
    if dated:
        latest = max(dated, key=lambda pair: pair[0])[0]
        return latest, "selected_latest"
    return None, "ambiguous"


def _json_values(rows: list[dict[str, Any]]) -> str:
    return json.dumps([{"value": row["value_normalized"] or row["value_raw"], "page": row["page_number"], "table": row["table_number"]} for row in rows], ensure_ascii=False, sort_keys=True)


def extract_features(run_root: Path, rules_path: Path) -> dict:
    registry = _rules(rules_path)
    extraction_root = run_root / "extracted"
    feature_root = run_root / "features"
    feature_root.mkdir(parents=True, exist_ok=True)
    occurrences: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    input_manifests = sorted((run_root / "files").glob("*.input.json"))
    ref_rows: dict[str, list[tuple]] = defaultdict(list)
    ledger_path = run_root / "ledger.duckdb"
    if ledger_path.exists():
        ledger = duckdb.connect(str(ledger_path), read_only=True)
        try:
            for response_hash, job_id in ledger.execute("SELECT response_hash, job_id FROM download_jobs WHERE response_hash IS NOT NULL").fetchall():
                for row in ledger.execute("SELECT ocid, release_id, document_id, source_url FROM download_job_refs WHERE job_id = ?", [job_id]).fetchall():
                    ref_rows[response_hash].append(row)
        except duckdb.CatalogException:
            pass
        ledger.close()
    for input_path in input_manifests:
        metadata = json.loads(input_path.read_text(encoding="utf-8"))
        document_hash = Path(metadata["path"]).name
        doc_path = extraction_root / document_hash / "docling.json"
        if not doc_path.exists():
            continue
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        base = {"source_snapshot_sha256": metadata.get("source_snapshot_sha256"), "source_run_id": metadata.get("source_run_id"), "document_download_run_id": run_root.name, "extraction_run_id": run_root.name + ":features", "document_hash": document_hash, "document_id": "|".join(metadata.get("document_ids") or []), "source_url": metadata.get("source_url")}
        references = ref_rows.get(document_hash) or [(ocid, release_id, document_id, metadata.get("source_url")) for ocid in metadata.get("ocids") or [None] for release_id in metadata.get("release_ids") or [None] for document_id in ["|".join(metadata.get("document_ids") or [])]]
        for ocid, release_id, document_id, source_url in references:
            links.append({**base, "ocid": ocid, "release_id": release_id, "document_id": document_id, "source_url": source_url, "generated_at": utc_now()})
        document_occurrences = _occurrences(doc, registry, base)
        for ocid, release_id, document_id, source_url in references:
            occurrences.extend([
                {**row, "ocid": ocid, "release_id": release_id, "document_id": document_id, "source_url": source_url}
                for row in document_occurrences
            ])
        by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in document_occurrences:
            by_feature[row["feature_key"]].append(row)
        summary: dict[str, Any] = {**{column: None for column in SUMMARY_COLUMNS}, "source_snapshot_sha256": base["source_snapshot_sha256"], "source_run_id": base["source_run_id"], "document_hash": document_hash, "generated_at": utc_now()}
        conflict_count = 0
        ambiguity_count = 0
        for feature, rows in by_feature.items():
            primary, status = _primary(rows)
            if status == "ambiguous":
                ambiguity_count += 1
            if len({row["value_normalized"] for row in rows if row["value_normalized"]}) > 1:
                conflict_count += 1
            column = WIDE_FEATURES.get(feature)
            if column:
                summary[column] = primary
            if feature in {"lot_number", "lot_description"}:
                summary["lots_json"] = _json_values(rows)
            elif feature == "specification":
                summary["specifications_json"] = _json_values(rows)
            elif feature in {"quantity", "unit"}:
                summary["quantities_json"] = _json_values(rows)
            elif feature in {"eligibility_requirement", "required_registration", "required_experience", "required_certification", "agpo_category", "mandatory_site_visit"}:
                summary["eligibility_json"] = _json_values(rows)
            elif feature in {"evaluation_criteria", "technical_threshold", "financial_evaluation"}:
                summary["evaluation_criteria_json"] = _json_values(rows)
            elif feature.endswith("_term"):
                summary["ict_terms_json"] = _json_values(rows)
        summary["occurrence_count"] = len(document_occurrences)
        summary["conflict_count"] = conflict_count
        summary["ambiguity_count"] = ambiguity_count
        summary["quality_status"] = "observed" if document_occurrences else "no_features_observed"
        summaries.append(summary)
    connection = duckdb.connect()
    for name, rows, columns in (("document_feature_occurrences", occurrences, OCCURRENCE_COLUMNS), ("document_feature_links", links, LINK_COLUMNS), ("document_feature_summary", summaries, SUMMARY_COLUMNS)):
        if rows:
            placeholders = ",".join("(" + ",".join("?" for _ in columns) + ")" for _ in rows)
            connection.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM (VALUES {placeholders}) AS t({','.join(columns)})", [row.get(column) for row in rows for column in columns])
        else:
            connection.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT " + ",".join(f"CAST(NULL AS VARCHAR) AS {column}" for column in columns) + " WHERE FALSE")
        connection.execute(f"COPY {name} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(feature_root / f"{name}.parquet")])
    parser_versions = sorted({
        json.loads(path.read_text(encoding="utf-8")).get("parser_version")
        for path in (extraction_root).glob("*/extraction_manifest.json")
        if json.loads(path.read_text(encoding="utf-8")).get("parser_version")
    })
    observed_features = set(row["feature_key"] for row in occurrences)
    configured_features = {rule["feature_key"] for rule in registry["rules"]}
    evidence_complete = sum(1 for row in occurrences if row["document_hash"] and (row["page_number"] is not None or row["table_number"] is not None) and row["evidence_text"])
    reference_counts = Counter(row["document_hash"] for row in links)
    report = {
        "run_root": str(run_root), "rules_path": str(rules_path), "rule_version": registry["rule_version"],
        "input_documents": len(input_manifests), "documents_with_features": len(summaries),
        "occurrence_count": len(occurrences), "link_count": len(links),
        "feature_counts": dict(Counter(row["feature_key"] for row in occurrences)),
        "conflict_count": sum(row["conflict_count"] or 0 for row in summaries),
        "ambiguity_count": sum(row["ambiguity_count"] or 0 for row in summaries),
        "quality_counts": dict(Counter(row["quality_status"] for row in summaries)),
        "missing_feature_keys": sorted(configured_features - observed_features),
        "evidence_completeness": {"complete_occurrences": evidence_complete, "total_occurrences": len(occurrences), "rate": evidence_complete / len(occurrences) if occurrences else 0.0},
        "ocr_derived_occurrences": sum(1 for row in occurrences if row["ocr_derived"] is True),
        "duplicate_content": {"unique_content_hashes": len(reference_counts), "referenced_more_than_once": sum(1 for count in reference_counts.values() if count > 1), "max_references": max(reference_counts.values(), default=0)},
        "parser_versions": parser_versions,
        "unparsed_documents": len(input_manifests) - len(summaries),
        "ocr_status": "unavailable_in_extraction_manifest",
        "source_limitations": [
            "Document-derived observations do not overwrite canonical OCDS values.",
            "OCR provenance is unavailable in the captured extraction manifests; ocr_derived remains unknown.",
            "Rule matches are lexical observations and require human review before evaluation claims.",
            "Feature materialization is incomplete while captured binaries lack Docling manifests.",
        ],
        "outputs": {name: str(feature_root / f"{name}.parquet") for name in ("document_feature_occurrences", "document_feature_summary", "document_feature_links")},
        "status": "pass" if len(summaries) == len(input_manifests) else "warn",
    }
    (run_root / "document_feature_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (run_root / "document_feature_report.md").write_text(render_report(report), encoding="utf-8")
    connection.close()
    return report


def render_report(report: dict[str, Any]) -> str:
    lines = ["# Document feature extraction report", "", f"Status: `{report['status']}`", f"Rule version: `{report['rule_version']}`", "", "## Counts", ""]
    lines.extend([f"- Input documents: {report['input_documents']}", f"- Documents with features: {report['documents_with_features']}", f"- Unparsed documents: {report['unparsed_documents']}", f"- Evidence occurrences: {report['occurrence_count']}", f"- Source links: {report['link_count']}", f"- Conflicts: {report['conflict_count']}", f"- Ambiguities: {report['ambiguity_count']}", "", "## Feature counts", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(report["feature_counts"].items()))
    lines.extend(["", "## Quality", "", f"- Evidence completeness: {report['evidence_completeness']['complete_occurrences']}/{report['evidence_completeness']['total_occurrences']} ({report['evidence_completeness']['rate']:.1%})", f"- OCR-derived occurrences: {report['ocr_derived_occurrences']}", f"- Unique content hashes: {report['duplicate_content']['unique_content_hashes']}", f"- Content hashes referenced more than once: {report['duplicate_content']['referenced_more_than_once']}", "", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report["source_limitations"])
    return "\n".join(lines) + "\n"


def report(run_root: Path) -> dict:
    return json.loads((run_root / "document_feature_report.json").read_text(encoding="utf-8"))
