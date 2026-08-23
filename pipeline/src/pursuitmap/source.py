from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .paths import RAW_ROOT, ensure_data_dirs


SOURCE_URL = "https://data.open-contracting.org/en/publication/143/download?name=full.jsonl.gz"
SOURCE_PAGE = "https://data.open-contracting.org/en/publication/143"
SOURCE_API = "https://ocds-api.etenders.gov.za/swagger/index.html"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(path: Path, *, source_url: str, source_path: Path) -> dict:
    manifest = {
        "source": "south_africa_national_treasury_ocpo",
        "source_url": source_url,
        "source_page": SOURCE_PAGE,
        "source_api": SOURCE_API,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "path": str(source_path.relative_to(RAW_ROOT.parent.parent)),
        "bytes": source_path.stat().st_size,
        "sha256": sha256_file(source_path),
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def ingest(source_url: str = SOURCE_URL, *, force: bool = False, local_path: Path | None = None) -> dict:
    ensure_data_dirs()
    destination = RAW_ROOT / ("ocds_full.jsonl" if local_path is not None and local_path.suffix != ".gz" else "ocds_full.jsonl.gz")
    if local_path is not None:
        shutil.copyfile(local_path, destination)
    elif destination.exists() and not force:
        manifest_path = RAW_ROOT / "manifest.json"
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        return write_manifest(RAW_ROOT / "manifest.json", source_url=source_url, source_path=destination)
    else:
        request = urllib.request.Request(source_url, headers={"User-Agent": "PursuitMap/0.1"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    return write_manifest(RAW_ROOT / "manifest.json", source_url=source_url, source_path=destination)
