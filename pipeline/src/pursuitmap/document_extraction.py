from __future__ import annotations

import json
import zipfile
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
    source_run_id: str | None = None
    parent_document_hash: str | None = None
    archive_member: str | None = None


def _require_docling():
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as error:
        raise RuntimeError("Docling is required. Install with `uv sync --extra documents`.") from error
    return DocumentConverter


def _make_converter(*, enable_ocr: bool):
    converter_class = _require_docling()
    if enable_ocr:
        return converter_class()
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import PdfFormatOption

    options = PdfPipelineOptions(do_ocr=False)
    return converter_class(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


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
        "source_run_id": document.source_run_id,
        "parent_document_hash": document.parent_document_hash,
        "archive_member": document.archive_member,
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


ARCHIVE_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".html", ".htm", ".txt", ".md"}


def _expand_archive(document: DocumentInput, run_root: Path) -> tuple[list[DocumentInput], list[dict]]:
    """Extract supported archive members into a content-addressed staging area."""
    parent_hash = sha256_file(document.path)
    expanded_root = run_root / "expanded" / parent_hash
    children: list[DocumentInput] = []
    warnings: list[dict] = []
    try:
        archive = zipfile.ZipFile(document.path)
    except zipfile.BadZipFile as error:
        return [], [{"member": None, "error_type": type(error).__name__, "error": str(error)}]
    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            suffix = member_path.suffix.lower()
            if suffix not in ARCHIVE_SUFFIXES:
                warnings.append({"member": member.filename, "status": "unsupported_suffix", "suffix": suffix})
                continue
            if member_path.is_absolute() or ".." in member_path.parts:
                warnings.append({"member": member.filename, "status": "unsafe_path"})
                continue
            payload = archive.read(member)
            child_hash = __import__("hashlib").sha256(payload).hexdigest()
            child_path = expanded_root / f"{child_hash}{suffix}"
            child_path.parent.mkdir(parents=True, exist_ok=True)
            if not child_path.exists():
                child_path.write_bytes(payload)
            children.append(DocumentInput(
                path=child_path,
                source_url=document.source_url,
                source_snapshot_sha256=document.source_snapshot_sha256,
                ocid=document.ocid,
                release_id=document.release_id,
                document_id=document.document_id,
                source_run_id=document.source_run_id,
                parent_document_hash=parent_hash,
                archive_member=member.filename,
            ))
            child_manifest = run_root / "files" / f"{child_hash}.archive.input.json"
            if not child_manifest.exists():
                child_manifest.write_text(json.dumps({
                    "path": str(child_path), "source_url": document.source_url,
                    "source_run_id": document.source_run_id,
                    "source_snapshot_sha256": document.source_snapshot_sha256,
                    "ocids": document.ocid.split("|") if document.ocid else [],
                    "release_ids": document.release_id.split("|") if document.release_id else [],
                    "document_ids": document.document_id.split("|") if document.document_id else [],
                    "response_hash": child_hash, "parent_document_hash": parent_hash,
                    "archive_member": member.filename, "status": "captured",
                }, indent=2) + "\n", encoding="utf-8")
    return children, warnings


def extract_document(document: DocumentInput, output_dir: Path) -> dict:
    """Convert one captured document and write content-addressed outputs."""
    return _write_extraction(document, output_dir, _require_docling()())


def extract_documents(documents: list[DocumentInput], output_dir: Path) -> list[dict]:
    """Convert a batch with one converter instance and content-addressed outputs."""
    converter = _require_docling()()
    return [_write_extraction(document, output_dir, converter) for document in documents]


def parse_run(run_root: Path, *, limit: int | None = None, skip_hashes: tuple[str, ...] = (), enable_ocr: bool = False) -> dict:
    """Parse captured content hashes once and record resumable progress."""
    input_paths = sorted((run_root / "files").glob("*.input.json"))
    output_dir = run_root / "extracted"
    output_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    skipped = 0
    previous_progress_path = run_root / "document_extraction_progress.json"
    previous_progress = json.loads(previous_progress_path.read_text(encoding="utf-8")) if previous_progress_path.exists() else {}
    skipped_hashes = set(skip_hashes) | set(previous_progress.get("skip_hashes") or [])
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
            source_run_id=metadata.get("source_run_id"),
        ))
    pending.sort(key=lambda document: (document.path.stat().st_size, sha256_file(document.path)))
    progress = {"run_root": str(run_root), "input_documents": len(input_paths), "skipped": skipped, "skip_hashes": sorted(skipped_hashes), "pending": len(pending), "processed": 0, "parsed": 0, "failed": 0, "archives_expanded": 0, "archive_members": 0, "archive_warnings": 0, "ocr_enabled": enable_ocr, "status": "running", "updated_at": utc_now()}
    progress_path = run_root / "document_extraction_progress.json"
    progress_path.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    failures = []
    converter = _make_converter(enable_ocr=enable_ocr) if pending else None
    for index, document in enumerate(pending):
        document_hash = sha256_file(document.path)
        try:
            documents = [document]
            if zipfile.is_zipfile(document.path):
                documents, warnings = _expand_archive(document, run_root)
                progress["archives_expanded"] += 1
                progress["archive_members"] += len(documents)
                progress["archive_warnings"] += len(warnings)
                if not documents:
                    raise ValueError("archive contains no supported document members")
            for child in documents:
                child_hash = sha256_file(child.path)
                if child_hash in skipped_hashes or (output_dir / child_hash / "extraction_manifest.json").exists():
                    continue
                _write_extraction(child, output_dir, converter)
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
