from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import duckdb


ROLE_LABELS = {
    "tender_notice", "tender_document", "addendum", "rfp", "technical_specification",
    "financial_proposal", "evaluation_record", "contract", "framework_agreement",
    "supplier_registration", "meeting_minutes", "form", "correspondence", "unknown",
}
STOPWORDS = {"and", "the", "for", "with", "from", "that", "this", "are", "will", "shall", "not", "you", "all", "can", "may", "but", "into", "has", "have", "was", "were", "been", "their", "your", "its", "www", "com", "pdf"}


def _tokens(text: str) -> Counter[str]:
    return Counter(token for token in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if token not in STOPWORDS)


def _cosine(left: dict[str, float], right: dict[str, float], left_norm: float, right_norm: float) -> float:
    if not left_norm or not right_norm:
        return 0.0
    return sum(value * right.get(key, 0.0) for key, value in left.items()) / (left_norm * right_norm)


def _union_find(size: int, edges: list[tuple[int, int]]) -> list[int]:
    parent = list(range(size))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for left, right in edges:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root
    roots = {root: index for index, root in enumerate(sorted({find(i) for i in range(size)}), 1)}
    return [roots[find(i)] for i in range(size)]


def analyze_classification(run_root: Path, classification_dir: Path, *, threshold: float = 0.45) -> dict:
    records = []
    for path in sorted(classification_dir.glob("batch-*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    hashes = [record["document_hash"] for record in records]
    if len(records) != len(set(hashes)):
        raise ValueError("classification batches contain duplicate document hashes")
    invalid = sorted({record.get("document_role") for record in records} - ROLE_LABELS)
    if invalid:
        raise ValueError(f"unsupported document roles: {invalid}")

    token_counts = []
    for record in records:
        markdown = run_root / "extracted" / record["document_hash"] / "document.md"
        token_counts.append(_tokens(markdown.read_text(encoding="utf-8") if markdown.exists() else ""))
    document_frequency = Counter(token for counts in token_counts for token in counts)
    vectors = []
    norms = []
    for counts in token_counts:
        vector = {token: (1 + math.log(count)) * math.log((1 + len(records)) / (1 + document_frequency[token])) for token, count in counts.items()}
        vectors.append(vector)
        norms.append(math.sqrt(sum(value * value for value in vector.values())))
    edges = []
    similarities = []
    for left in range(len(records)):
        best = (None, 0.0)
        for right in range(len(records)):
            if left >= right:
                continue
            similarity = _cosine(vectors[left], vectors[right], norms[left], norms[right])
            if similarity > best[1]:
                best = (right, similarity)
            if similarity >= threshold:
                edges.append((left, right))
                similarities.append({"left_hash": hashes[left], "right_hash": hashes[right], "cosine_similarity": similarity})
        records[left]["nearest_neighbor_hash"] = hashes[best[0]] if best[0] is not None else None
        records[left]["nearest_neighbor_similarity"] = best[1]
    cluster_ids = _union_find(len(records), edges)
    for index, record in enumerate(records):
        record["similarity_cluster_id"] = cluster_ids[index]
    cluster_sizes = Counter(cluster_ids)
    for record in records:
        record["similarity_cluster_size"] = cluster_sizes[record["similarity_cluster_id"]]

    role_indices = defaultdict(list)
    for index, record in enumerate(records):
        role_indices[record["document_role"]].append(index)
    role_cohesion = {}
    for role, indices in role_indices.items():
        values = [_cosine(vectors[left], vectors[right], norms[left], norms[right]) for position, left in enumerate(indices) for right in indices[position + 1:]]
        role_cohesion[role] = {"documents": len(indices), "mean_pairwise_similarity": sum(values) / len(values) if values else None, "pairs": len(values)}

    feature_rows = []
    occurrence_path = run_root / "features" / "document_feature_occurrences.parquet"
    if occurrence_path.exists():
        connection = duckdb.connect()
        feature_rows = connection.execute("""
            SELECT c.document_role, o.feature_key, count(*) AS occurrences, count(DISTINCT o.document_hash) AS documents
            FROM read_parquet(?) o JOIN read_json_auto(?) c ON o.document_hash = c.document_hash
            GROUP BY 1, 2 ORDER BY 1, 3 DESC
        """, [str(occurrence_path), [str(path) for path in sorted(classification_dir.glob("batch-*.jsonl"))]]).fetchall()
        connection.close()

    output_dir = run_root / "classification"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "document_classification.jsonl").write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")
    (output_dir / "document_similarity_edges.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in similarities) + ("\n" if similarities else ""), encoding="utf-8")
    report = {"input_documents": len(records), "role_counts": dict(Counter(record["document_role"] for record in records)), "confidence_counts": dict(Counter(record["confidence"] for record in records)), "standardized_count": sum(record.get("likely_standard_template") is True for record in records), "cluster_count": len(cluster_sizes), "cluster_sizes": dict(sorted(cluster_sizes.items())), "similarity_threshold": threshold, "similarity_edges": len(similarities), "role_cohesion": role_cohesion, "role_feature_coverage": [{"document_role": role, "feature_key": feature, "occurrences": occurrences, "documents": documents} for role, feature, occurrences, documents in feature_rows], "outputs": {"classification": str(output_dir / "document_classification.jsonl"), "similarity_edges": str(output_dir / "document_similarity_edges.jsonl")}}
    (output_dir / "document_classification_analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _load_classification(directory: Path) -> dict[str, dict]:
    rows = {}
    for path in sorted(directory.glob("batch-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["document_hash"]] = row
    return rows


def compare_classifications(left_dir: Path, right_dir: Path, output_path: Path) -> dict:
    left, right = _load_classification(left_dir), _load_classification(right_dir)
    if set(left) != set(right):
        raise ValueError("classification passes do not cover the same document hashes")
    confusion = Counter()
    changes = []
    confidence_changes = Counter()
    standardization_changes = Counter()
    for document_hash in sorted(left):
        left_role, right_role = left[document_hash]["document_role"], right[document_hash]["document_role"]
        confusion[(left_role, right_role)] += 1
        if left_role != right_role:
            changes.append({"document_hash": document_hash, "left_role": left_role, "right_role": right_role, "left_evidence": left[document_hash].get("role_evidence", []), "right_evidence": right[document_hash].get("role_evidence", [])})
        confidence_changes[(left[document_hash].get("confidence"), right[document_hash].get("confidence"))] += 1
        standardization_changes[(bool(left[document_hash].get("likely_standard_template")), bool(right[document_hash].get("likely_standard_template")))] += 1
    report = {
        "documents": len(left),
        "role_agreement_count": sum(value for (left_role, right_role), value in confusion.items() if left_role == right_role),
        "role_agreement_rate": sum(value for (left_role, right_role), value in confusion.items() if left_role == right_role) / len(left),
        "role_confusion": [{"left_role": left_role, "right_role": right_role, "count": count} for (left_role, right_role), count in sorted(confusion.items())],
        "role_changes": changes,
        "confidence_changes": [{"left": left_value, "right": right_value, "count": count} for (left_value, right_value), count in sorted(confidence_changes.items())],
        "standardization_changes": [{"left": left_value, "right": right_value, "count": count} for (left_value, right_value), count in sorted(standardization_changes.items())],
        "left_directory": str(left_dir),
        "right_directory": str(right_dir),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
