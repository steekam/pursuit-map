from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from . import __version__
from .paths import WORKING_ROOT


TRANSFORM_VERSION = "phase1.1"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hash(source_path: Path, manifest_path: Path | None = None) -> str:
    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sha256"):
            return manifest["sha256"]
    return sha256_file(source_path)


def run_id(source_sha256: str, operation: str) -> str:
    return f"{operation}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{source_sha256[:12]}"


def environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "duckdb": duckdb.__version__,
        "pursuitmap": __version__,
        "transform_version": TRANSFORM_VERSION,
    }


def parquet_checksums(parquet_root: Path) -> dict[str, str]:
    return {
        path.name: sha256_file(path)
        for path in sorted(parquet_root.glob("*.parquet"))
    }


def write_run_manifest(operation: str, source_sha256: str, payload: dict) -> tuple[str, Path]:
    run = run_id(source_sha256, operation)
    run_dir = WORKING_ROOT / "runs" / run
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run,
        "operation": operation,
        "source_snapshot_sha256": source_sha256,
        "generated_at": utc_now(),
        "environment": environment(),
        **payload,
    }
    path = run_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return run, path
