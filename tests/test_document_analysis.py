import json

from pursuitmap.document_analysis import analyze_classification


def test_classification_analysis_is_deterministic(tmp_path):
    run_root = tmp_path / "run"
    for document_hash, text in (("a", "Tender notice submission deadline buyer"), ("b", "Tender notice submission deadline buyer"), ("c", "Supplier registration company details")):
        directory = run_root / "extracted" / document_hash
        directory.mkdir(parents=True)
        (directory / "document.md").write_text(text)
    classification_dir = tmp_path / "classification"
    classification_dir.mkdir()
    rows = [
        {"document_hash": "a", "document_role": "tender_notice", "confidence": "high", "likely_standard_template": True},
        {"document_hash": "b", "document_role": "tender_notice", "confidence": "high", "likely_standard_template": True},
        {"document_hash": "c", "document_role": "supplier_registration", "confidence": "medium", "likely_standard_template": False},
    ]
    (classification_dir / "batch-01.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    first = analyze_classification(run_root, classification_dir, threshold=0.45)
    second = analyze_classification(run_root, classification_dir, threshold=0.45)
    assert first["cluster_count"] == second["cluster_count"]
    assert first["role_counts"] == {"tender_notice": 2, "supplier_registration": 1}
    assert (run_root / "classification" / "document_classification.jsonl").exists()
