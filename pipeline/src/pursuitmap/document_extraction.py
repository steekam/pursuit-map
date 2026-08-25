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


def parse_run(run_root: Path, *, limit: int | None = None, skip_hashes: tuple[str, ...] = ()) -> dict:
    """Parse captured content hashes once and record resumable progress."""
    input_paths = sorted((run_root / "files").glob("*.input.json"))
    output_dir = run_root / "extracted"
    output_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    skipped = 0
    skipped_hashes = set(skip_hashes)
    for input_path in input_paths:
        metadata = json.loads(input_path.read_text(encoding="utf-8"))
        document_hash = metadata.get("response_hash") or Path(metadata["path"]).name
        if document_hash in skipped_hashes or (output_dir / document_hash / "extraction_manifest.json").exists():
            skipped += 1
            continue
        pending.append(DocumentInput(
            path=Path(metadata["path"]),
            source_url=metadata["source_url"],
            source_snapshot_sha256=metadata.get("source_snapshot_sha256", "unknown"),
            ocid="|".join(metadata.get("ocids") or []),
            release_id="|".join(metadata.get("release_ids") or []),
            document_id="|".join(metadata.get("document_ids") or []),
        ))
    progress = {"run_root": str(run_root), "input_documents": len(input_paths), "skipped": skipped, "pending": len(pending), "processed": 0, "parsed": 0, "failed": 0, "status": "running", "updated_at": utc_now()}
    progress_path = run_root / "document_extraction_progress.json"
    progress_path.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    failures = []
    converter = _require_docling()() if pending else None
    for index, document in enumerate(pending):
        document_hash = sha256_file(document.path)
        try:
            _write_extraction(document, output_dir, converter)
            progress["parsed"] += 1
        except Exception as error:
            failures.append({"document_hash": document_hash, "path": str(document.path), "error_type": type(error).__name__, "error": str(error)})
            progress["failed"] += 1
        progress.update({"processed": index + 1, "remaining": len(pending) - index - 1, "current_hash": document_hash, "updated_at": utc_now()})
        progress_path.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
        if limit is not None and index + 1 >= limit:
            break
    if failures:
        (run_root / "document_extraction_failures.json").write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    complete = progress["processed"] == len(pending)
    progress.update({"total_parsed": skipped + progress["parsed"], "status": "warn" if failures else ("pass" if complete else "paused_limit"), "updated_at": utc_now()})
    progress_path.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    return progress


def write_input_manifest(document: DocumentInput, output_path: Path) -> Path:
    """Record a captured input before extraction begins."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    value = {**asdict(document), "path": str(document.path), "status": "captured"}
    output_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return output_path
