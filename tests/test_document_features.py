import json

import duckdb

from pursuitmap import document_extraction
from pursuitmap.document_features import _primary, _units, extract_features


def test_units_follow_docling_body_order_and_preserve_table_coordinates():
    doc = {
        "texts": [
            {"self_ref": "#/texts/0", "label": "section_header", "text": "NOTICE", "prov": [{"page_no": 2, "bbox": {"coord_origin": "BOTTOMLEFT"}}]},
            {"self_ref": "#/texts/1", "label": "text", "text": "Closing date: 4 August 2026", "prov": [{"page_no": 2, "bbox": {"coord_origin": "TOPLEFT"}}]},
        ],
        "tables": [{"self_ref": "#/tables/0", "prov": [{"page_no": 3, "bbox": {"coord_origin": "TOPLEFT"}}], "data": {"table_cells": [{"text": "Lot 1", "start_row_offset_idx": 2, "start_col_offset_idx": 1, "bbox": {"coord_origin": "TOPLEFT"}}]}}],
        "groups": [{"self_ref": "#/groups/0", "children": [{"$ref": "#/texts/1"}]}],
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/groups/0"}, {"$ref": "#/tables/0"}]},
    }
    units = _units(doc)
    assert [unit["text"] for unit in units] == ["NOTICE", "Closing date: 4 August 2026", "Lot 1"]
    assert units[-1]["page"] == 3
    assert units[-1]["row"] == 2
    assert units[-1]["column"] == 1
    assert units[-1]["origin"] == "TOPLEFT"


def test_ambiguous_non_date_primary_is_null():
    values = [{"value_normalized": "one", "value_type": "text"}, {"value_normalized": "two", "value_type": "text"}]
    assert _primary(values) == (None, "ambiguous")


def test_extract_features_writes_evidence_links_and_summary(tmp_path):
    run_root = tmp_path / "run"
    files = run_root / "files"
    extracted = run_root / "extracted" / "abc"
    files.mkdir(parents=True)
    extracted.mkdir(parents=True)
    (files / "abc.input.json").write_text(json.dumps({"path": str(files / "abc"), "source_run_id": "source", "source_snapshot_sha256": "snapshot", "source_url": "https://example.test/a.pdf", "ocids": ["ocid"], "release_ids": ["release"], "document_ids": ["doc"]}))
    (extracted / "docling.json").write_text(json.dumps({"texts": [{"self_ref": "#/texts/0", "label": "text", "text": "Tender No: ABC/1. Closing date: 4 August 2026", "prov": [{"page_no": 1, "bbox": {"coord_origin": "TOPLEFT"}}]}], "tables": [], "body": {"children": [{"$ref": "#/texts/0"}]}}))
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rule_version": "test-1", "rules": [{"feature_key": "tender_number", "family": "identity", "value_type": "identifier", "patterns": ["tender no"]}, {"feature_key": "submission_deadline", "family": "timing", "value_type": "datetime", "patterns": ["closing date"]}]}))
    report = extract_features(run_root, rules)
    assert report["occurrence_count"] == 2
    connection = duckdb.connect()
    occurrences = connection.execute("select feature_key, page_number, coordinate_origin from read_parquet(?) order by feature_key", [str(run_root / "features/document_feature_occurrences.parquet")]).fetchall()
    assert occurrences == [("submission_deadline", 1, "TOPLEFT"), ("tender_number", 1, "TOPLEFT")]
    links = connection.execute("select count(*) from read_parquet(?)", [str(run_root / "features/document_feature_links.parquet")]).fetchone()[0]
    assert links == 1


def test_batch_extraction_reuses_one_converter(monkeypatch, tmp_path):
    class FakeDocument:
        def save_as_json(self, path):
            open(path, "w", encoding="utf-8").write(json.dumps({"version": "1.10.0"}))

        def export_to_markdown(self):
            return "document"

        def model_dump(self):
            return {"version": "1.10.0"}

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        instances = 0

        def __init__(self):
            FakeConverter.instances += 1

        def convert(self, path):
            return FakeResult()

    monkeypatch.setattr(document_extraction, "_require_docling", lambda: FakeConverter)
    inputs = []
    for index in range(2):
        path = tmp_path / f"{index}.pdf"
        path.write_bytes(f"pdf-{index}".encode())
        inputs.append(document_extraction.DocumentInput(path, "url", "snapshot", "ocid", "release", f"doc-{index}"))
    manifests = document_extraction.extract_documents(inputs, tmp_path / "out")
    assert len(manifests) == 2
    assert FakeConverter.instances == 1
    assert all(manifest["parser_version"] == document_extraction.PARSER_VERSION for manifest in manifests)
