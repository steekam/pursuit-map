from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parents[3] / "config" / "verticals" / "ict.json"
TOKEN_RE = re.compile(r"[a-z0-9]+")


def load_taxonomy(path: str | Path | None = None) -> dict[str, Any]:
    taxonomy_path = Path(path) if path is not None else DEFAULT_TAXONOMY_PATH
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Taxonomy must be a JSON object")
    if not isinstance(payload.get("version"), str) or not payload["version"]:
        raise ValueError("Taxonomy version is required")
    if not isinstance(payload.get("categories"), list) or not payload["categories"]:
        raise ValueError("Taxonomy categories are required")
    if not isinstance(payload.get("field_weights"), dict) or not payload["field_weights"]:
        raise ValueError("Taxonomy field_weights are required")
    return payload


def _text_parts(value: object) -> list[str]:
    parts: list[str] = []
    if value is None:
        return parts
    if isinstance(value, str):
        if value.strip():
            parts.append(value)
        return parts
    if isinstance(value, (int, float, bool)):
        parts.append(str(value))
        return parts
    if isinstance(value, Mapping):
        for key in sorted(value, key=lambda item: str(item)):
            parts.extend(_text_parts(value[key]))
        return parts
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            parts.extend(_text_parts(item))
        return parts
    parts.append(str(value))
    return parts


def _normalize_text(value: object) -> str:
    tokens: list[str] = []
    for part in _text_parts(value):
        tokens.extend(TOKEN_RE.findall(part.lower()))
    return " ".join(tokens)


def _resolve_path(record: Mapping[str, object], path: str) -> object | None:
    current: object = record
    for segment in path.split("."):
        if not isinstance(current, Mapping):
            return None
        if segment not in current:
            return None
        current = current[segment]
    return current


@lru_cache(maxsize=1024)
def _normalized_term(term: str) -> str:
    return _normalize_text(term)


@lru_cache(maxsize=1024)
def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(_normalized_term(term))
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


def _count_term(text: str, term: str) -> int:
    normalized = _normalized_term(term)
    if not normalized:
        return 0
    return len(_term_pattern(term).findall(text))


def _term_spec(term: object) -> tuple[str, float]:
    if isinstance(term, Mapping):
        label = str(term.get("term", "")).strip()
        weight = float(term.get("weight", 1.0))
    else:
        label = str(term).strip()
        weight = 1.0
    return label, weight


def _field_text(record: Mapping[str, object], path: str) -> str:
    value = _resolve_path(record, path)
    if value is None:
        return ""
    return _normalize_text(value)


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _score_category(
    record: Mapping[str, object],
    category: Mapping[str, object],
    field_weights: Mapping[str, object],
    global_exclusions: Sequence[object],
    blocked_categories: set[str],
) -> dict[str, Any]:
    category_id = str(category.get("id", "")).strip()
    category_label = str(category.get("label", category_id)).strip()
    include_terms = list(category.get("include_terms") or [])
    exclude_terms = list(global_exclusions) + list(category.get("exclude_terms") or [])
    score_breakdown: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    matched_terms: list[str] = []
    matched_fields: list[str] = []
    raw_score = 0.0

    for field, field_weight_value in field_weights.items():
        field_weight = float(field_weight_value)
        text = _field_text(record, field)
        if not text:
            continue
        field_matched = False
        for term in include_terms:
            term_label, term_weight = _term_spec(term)
            if not term_label:
                continue
            count = _count_term(text, term_label)
            if count <= 0:
                continue
            score = count * field_weight * term_weight
            raw_score += score
            field_matched = True
            matched_terms.append(term_label)
            score_breakdown.append(
                {
                    "field": field,
                    "term": term_label,
                    "count": count,
                    "field_weight": field_weight,
                    "term_weight": term_weight,
                    "score": score,
                }
            )
        for term in exclude_terms:
            term_label, _ = _term_spec(term)
            if not term_label:
                continue
            count = _count_term(text, term_label)
            if count <= 0:
                continue
            exclusions.append(
                {
                    "field": field,
                    "term": term_label,
                    "count": count,
                }
            )
            field_matched = True
        if field_matched:
            matched_fields.append(field)

    excluded_by: list[str] = []
    if exclusions:
        excluded_by.append("exclusion_terms")
    if category_id in blocked_categories:
        excluded_by.append("blocked_category")
    excluded = bool(excluded_by)
    score = 0.0 if excluded else raw_score

    return {
        "category_id": category_id,
        "category_label": category_label,
        "raw_score": raw_score,
        "score": score,
        "excluded": excluded,
        "excluded_by": excluded_by,
        "matched_terms": _unique(matched_terms),
        "matched_fields": _unique(matched_fields),
        "score_breakdown": score_breakdown,
        "exclusions": exclusions,
    }


def _taxonomy(
    taxonomy: Mapping[str, object] | None = None,
    taxonomy_path: str | Path | None = None,
) -> dict[str, Any]:
    if taxonomy is not None:
        return dict(taxonomy)
    return load_taxonomy(taxonomy_path)


def score_record(
    record: Mapping[str, object],
    taxonomy: Mapping[str, object] | None = None,
    *,
    taxonomy_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved = _taxonomy(taxonomy, taxonomy_path)
    field_weights = resolved["field_weights"]
    categories = resolved["categories"]
    global_exclusions = resolved.get("global_exclusions") or []
    blocked_categories = set(resolved.get("blocked_categories") or [])
    category_scores = [
        _score_category(record, category, field_weights, global_exclusions, blocked_categories)
        for category in categories
    ]
    top_category = max(
        category_scores,
        key=lambda item: (item["raw_score"], -categories.index(next(cat for cat in categories if str(cat.get("id", "")) == item["category_id"]))),
    )
    best_categories = [item for item in category_scores if not item["excluded"] and item["score"] > 0]
    best_category = max(
        best_categories,
        key=lambda item: (
            item["score"],
            item["raw_score"],
            -categories.index(next(cat for cat in categories if str(cat.get("id", "")) == item["category_id"])),
        ),
    ) if best_categories else None

    record_id = record.get("id") or record.get("record_id") or record.get("ocid")
    result = {
        "record_id": record_id,
        "taxonomy_version": resolved["version"],
        "decision": "include" if best_category is not None else "exclude",
        "top_category": top_category,
        "best_category": best_category,
        "top_score": top_category["raw_score"],
        "best_score": best_category["score"] if best_category is not None else 0.0,
        "category_scores": category_scores,
    }
    if "evidence" in record:
        result["evidence"] = record["evidence"]
    if "metadata" in record:
        result["metadata"] = record["metadata"]
    return result


def score_records(
    records: Sequence[Mapping[str, object]],
    taxonomy: Mapping[str, object] | None = None,
    *,
    taxonomy_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    resolved = _taxonomy(taxonomy, taxonomy_path)
    scored = [
        score_record(record, resolved)
        for record in records
    ]
    indexed = list(enumerate(scored))
    indexed.sort(
        key=lambda item: (
            -float(item[1]["best_score"]),
            -float(item[1]["top_score"]),
            str(item[1]["record_id"] or ""),
            item[0],
        )
    )
    return [item[1] for item in indexed]
