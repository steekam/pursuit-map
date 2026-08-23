import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class CountryPaths:
    raw: Path
    working: Path
    parquet: Path
    materialized: Path
    enriched: Path


COUNTRY_SLUGS = {"za": "south_africa", "ke": "kenya"}


def country_paths(country: str = "za") -> CountryPaths:
    try:
        slug = COUNTRY_SLUGS[country]
    except KeyError as error:
        raise ValueError(f"Unknown country: {country}") from error
    return CountryPaths(
        raw=DATA_ROOT / "raw" / slug,
        working=DATA_ROOT / "working" / slug,
        parquet=DATA_ROOT / "parquet" / slug,
        materialized=DATA_ROOT / "materialized" / slug,
        enriched=DATA_ROOT / "enriched" / slug,
    )


_ZA_PATHS = country_paths()
RAW_ROOT = _ZA_PATHS.raw
WORKING_ROOT = _ZA_PATHS.working
PARQUET_ROOT = _ZA_PATHS.parquet
MATERIALIZED_ROOT = _ZA_PATHS.materialized


def ensure_data_dirs(country: str = "za") -> None:
    roots = country_paths(country)
    for path in (roots.raw, roots.working, roots.parquet, roots.materialized, roots.enriched):
        path.mkdir(parents=True, exist_ok=True)


def canonical_root(country: str = "za", run_id: str | None = None) -> Path:
    """Resolve an immutable canonical snapshot, defaulting to the latest run."""
    roots = country_paths(country)
    if run_id:
        root = roots.parquet / run_id
    else:
        manifest_path = roots.working / "normalization_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Run `pursuitmap normalize {country}` before reading canonical tables.")
        root = Path(json.loads(manifest_path.read_text(encoding="utf-8"))["parquet_root"])
    if not root.is_dir():
        raise FileNotFoundError(f"Canonical output directory not found: {root}")
    return root
