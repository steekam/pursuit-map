import json

import pytest

from pursuitmap.document_extraction import DocumentInput, extract_document


def test_missing_document_fails_before_parser_import(tmp_path):
    document = DocumentInput(tmp_path / "missing.pdf", "https://example.test/a.pdf", "snapshot", "ocid", "release", "doc")
    with pytest.raises(FileNotFoundError):
        extract_document(document, tmp_path / "out")


def test_extraction_is_content_addressed_and_records_provenance(monkeypatch, tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    output = tmp_path / "out"

    class FakeDocument:
        def save_as_json(self, path):
            open(path, "w", encoding="utf-8").write(json.dumps({"pages": []}))

        def export_to_markdown(self):
            return "# Fixture\n"

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path):
            assert path == str(source)
            return FakeResult()

    monkeypatch.setattr("pursuitmap.document_extraction._require_docling", lambda: FakeConverter)
    value = extract_document(DocumentInput(source, "https://example.test/a.pdf", "snapshot", "ocid", "release", "doc"), output)
    artifact_dir = output / value["input_sha256"]
    assert value["status"] == "success"
    assert value["parser"] == "docling"
    assert (artifact_dir / "docling.json").exists()
    assert (artifact_dir / "document.md").read_text() == "# Fixture\n"
    assert json.loads((artifact_dir / "extraction_manifest.json").read_text())["source_url"] == "https://example.test/a.pdf"
