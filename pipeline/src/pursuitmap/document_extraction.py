from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from dataclasses import asdict, dataclass
from pathlib import Path

from .provenance import sha256_file, utc_now


PARSER_NAME = "docling"
try:
    PARSER_VERSION = version("docling")
except PackageNotFoundError:
    PARSER_VERSION = "unknown"


@dataclass(frozen=True)
class DocumentInput:
    path: Path
    source_url: str
    source_snapshot_sha256: str
    ocid: str
    release_id: str
    document_id: str


def _require_docling():
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as error:
        raise RuntimeError("Docling is required. Install with `uv sync --extra documents`.") from error
    return DocumentConverter


def _write_extraction(document: DocumentInput, output_dir: Path, converter: object) -> dict:
    """Convert one captured document with a supplied converter."""
    if not document.path.is_file():
        raise FileNotFoundError(document.path)
    input_sha256 = sha256_file(document.path)
    artifact_dir = output_dir / input_sha256
    artifact_dir.mkdir(parents=True, exist_ok=True)
    json_path = artifact_dir / "docling.json"
    markdown_path = artifact_dir / "document.md"
    manifest_path = artifact_dir / "extraction_manifest.json"
    result = converter.convert(str(document.path))
    result.document.save_as_json(str(json_path))
    markdown_path.write_text(result.document.export_to_markdown(), encoding="utf-8")
    document_dump = result.document.model_dump() if hasattr(result.document, "model_dump") else {}
    manifest = {
        "source_snapshot_sha256": document.source_snapshot_sha256,
        "source_url": document.source_url,
        "ocid": document.ocid,
        "release_id": document.release_id,
        "document_id": document.document_id,
        "input_path": str(document.path),
        "input_sha256": input_sha256,
        "parser": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "docling_json_schema_version": document_dump.get("version"),
        "conversion_options": {"ocr": "docling-default", "tables": "docling-default"},
        "outputs": {
            "json": {"path": str(json_path), "sha256": sha256_file(json_path)},
            "markdown": {"path": str(markdown_path), "sha256": sha256_file(markdown_path)},
        },
        "generated_at": utc_now(),
        "status": "success",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def extract_document(document: DocumentInput, output_dir: Path) -> dict:
    """Convert one captured document and write content-addressed outputs."""
    return _write_extraction(document, output_dir, _require_docling()())


def extract_documents(documents: list[DocumentInput], output_dir: Path) -> list[dict]:
    """Convert a batch with one converter instance and content-addressed outputs."""
    converter = _require_docling()()
    return [_write_extraction(document, output_dir, converter) for document in documents]


def write_input_manifest(document: DocumentInput, output_path: Path) -> Path:
    """Record a captured input before extraction begins."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    value = {**asdict(document), "path": str(document.path), "status": "captured"}
    output_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return output_path
