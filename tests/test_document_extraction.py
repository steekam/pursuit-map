import json
import zipfile

import pytest

from pursuitmap.document_extraction import DocumentInput, extract_document, parse_run


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


def test_parse_run_uses_one_converter_and_writes_progress(monkeypatch, tmp_path):
    run_root = tmp_path / "run"
    files = run_root / "files"
    files.mkdir(parents=True)
    source = files / "abc"
    source.write_bytes(b"fixture")
    (files / "abc.input.json").write_text(json.dumps({
        "path": str(source), "source_url": "https://example.test/a.pdf",
        "source_snapshot_sha256": "snapshot", "ocids": ["ocid"],
        "release_ids": ["release"], "document_ids": ["doc"],
    }))
    created = 0

    class FakeDocument:
        def save_as_json(self, path):
            open(path, "w", encoding="utf-8").write(json.dumps({"pages": []}))

        def export_to_markdown(self):
            return "# Fixture\n"

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def __init__(self):
            nonlocal created
            created += 1

        def convert(self, path):
            return FakeResult()

    monkeypatch.setattr("pursuitmap.document_extraction._make_converter", lambda **kwargs: FakeConverter())
    value = parse_run(run_root)
    assert value["total_parsed"] == 1
    assert created == 1
    assert json.loads((run_root / "document_extraction_progress.json").read_text())["status"] == "pass"


def test_parse_run_can_checkpoint_and_skip_hash(monkeypatch, tmp_path):
    run_root = tmp_path / "run"
    files = run_root / "files"
    files.mkdir(parents=True)
    source = files / "abc"
    source.write_bytes(b"fixture")
    digest = __import__("hashlib").sha256(b"fixture").hexdigest()
    (files / "abc.input.json").write_text(json.dumps({"path": str(source), "response_hash": digest, "source_url": "https://example.test/a.pdf", "ocids": [], "release_ids": [], "document_ids": []}))
    value = parse_run(run_root, skip_hashes=(digest,))
    assert value["skipped"] == 1
    assert value["total_parsed"] == 1


def test_parse_run_expands_zip_members_and_preserves_parent_provenance(monkeypatch, tmp_path):
    run_root = tmp_path / "run"
    files = run_root / "files"
    files.mkdir(parents=True)
    source = files / "archive"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("notice.txt", "Tender notice")
        archive.writestr("readme.bin", b"ignored")
    (files / "archive.input.json").write_text(json.dumps({
        "path": str(source), "response_hash": "archive-response", "source_url": "https://example.test/archive.zip",
        "ocids": ["ocid"], "release_ids": ["release"], "document_ids": ["doc"],
    }))

    class FakeDocument:
        def save_as_json(self, path):
            open(path, "w", encoding="utf-8").write(json.dumps({"pages": []}))

        def export_to_markdown(self):
            return "# Archive member\n"

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path):
            assert path.endswith(".txt")
            return FakeResult()

    monkeypatch.setattr("pursuitmap.document_extraction._make_converter", lambda **kwargs: FakeConverter())
    value = parse_run(run_root)
    assert value["archives_expanded"] == 1
    assert value["archive_members"] == 1
    assert value["archive_warnings"] == 1
    assert value["parsed"] == 1
    manifests = list((run_root / "extracted").glob("*/extraction_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["parent_document_hash"]
    assert manifest["archive_member"] == "notice.txt"
