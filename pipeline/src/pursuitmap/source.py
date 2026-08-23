from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .paths import RAW_ROOT, country_paths, ensure_data_dirs


SOURCE_URL = "https://data.open-contracting.org/en/publication/143/download?name=full.jsonl.gz"
SOURCE_PAGE = "https://data.open-contracting.org/en/publication/143"
SOURCE_API = "https://ocds-api.etenders.gov.za/swagger/index.html"
COUNTRY_SOURCE = {
    "za": {"name": "south_africa_national_treasury_ocpo", "url": SOURCE_URL, "page": SOURCE_PAGE, "api": SOURCE_API},
    "ke": {"name": "kenya_ppra_ppip", "url": "https://fastly.data.open-contracting.org/downloads/kenya_ppra/4054/full.jsonl.gz", "page": "https://data.open-contracting.org/en/publication/147", "api": "https://tenders.go.ke/ocds"},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(path: Path, *, source_url: str, source_path: Path, country: str = "za") -> dict:
    source = COUNTRY_SOURCE[country]
    manifest = {
        "source": source["name"],
        "source_url": source_url,
        "source_page": source["page"],
        "source_api": source["api"],
        "retrieved_at": datetime.now(UTC).isoformat(),
        "path": str(source_path.relative_to(country_paths(country).raw.parent.parent)),
        "bytes": source_path.stat().st_size,
        "sha256": sha256_file(source_path),
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def ingest(source_url: str | None = None, *, country: str = "za", force: bool = False, local_path: Path | None = None) -> dict:
    ensure_data_dirs(country)
    roots = country_paths(country)
    source_url = source_url or COUNTRY_SOURCE[country]["url"]
    destination = roots.raw / ("ocds_full.jsonl" if local_path is not None and local_path.suffix != ".gz" else "ocds_full.jsonl.gz")
    if local_path is not None:
        shutil.copyfile(local_path, destination)
    elif destination.exists() and not force:
        manifest_path = roots.raw / "manifest.json"
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        return write_manifest(roots.raw / "manifest.json", source_url=source_url, source_path=destination, country=country)
    else:
        request = urllib.request.Request(source_url, headers={"User-Agent": "PursuitMap/0.1"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    return write_manifest(roots.raw / "manifest.json", source_url=source_url, source_path=destination, country=country)
