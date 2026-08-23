from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_baselines
from .enrichment import enrich
from .materialize import materialize
from .normalize import normalize
from .report import create_report
from .retrieval import available_verticals
from .search import search
from .source import ingest
from .source_enrichment import enrich_source
from .durable_source_enrichment import execute as source_enrich_execute
from .durable_source_enrichment import compatibility_enrich_source
from .durable_source_enrichment import plan as source_enrich_plan
from .durable_source_enrichment import report as source_enrich_report
from .durable_source_enrichment import resume as source_enrich_resume
from .verification import verify_outputs
from .document_download import plan as document_plan
from .document_download import run as document_run


def main() -> None:
    parser = argparse.ArgumentParser(prog="pursuitmap")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("country", choices=["za", "ke"])
    ingest_parser.add_argument("--url")
    ingest_parser.add_argument("--local-path", type=Path)
    ingest_parser.add_argument("--force", action="store_true")

    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("country", choices=["za", "ke"])
    normalize_parser.add_argument("--source-path", type=Path)

    report_parser = commands.add_parser("report")
    report_parser.add_argument("country", choices=["za", "ke"])

    profile_parser = commands.add_parser("profile")
    profile_parser.add_argument("country", choices=["za", "ke"])

    enrich_parser = commands.add_parser("enrich")
    enrich_parser.add_argument("country", choices=["za", "ke"])

    source_enrich_parser = commands.add_parser("enrich-source")
    source_enrich_parser.add_argument("country", choices=["ke"])
    source_enrich_parser.add_argument("--limit", type=int, default=20)
    source_enrich_parser.add_argument("--timeout", type=int, default=30)
    source_enrich_parser.add_argument("--ocid", action="append", dest="ocids")

    durable_parser = commands.add_parser("source-enrich")
    durable_subparsers = durable_parser.add_subparsers(dest="source_enrich_action", required=True)
    durable_plan = durable_subparsers.add_parser("plan")
    durable_plan.add_argument("country", choices=["ke"])
    durable_plan.add_argument("--limit", type=int, default=25)
    durable_run = durable_subparsers.add_parser("run")
    durable_run.add_argument("country", choices=["ke"])
    durable_run.add_argument("--run-id", required=True)
    durable_resume = durable_subparsers.add_parser("resume")
    durable_resume.add_argument("country", choices=["ke"])
    durable_resume.add_argument("--run-id", required=True)
    durable_report = durable_subparsers.add_parser("report")
    durable_report.add_argument("country", choices=["ke"])
    durable_report.add_argument("--run-id", required=True)

    materialize_parser = commands.add_parser("materialize")
    materialize_parser.add_argument("country", choices=["za"])

    search_parser = commands.add_parser("search")
    search_parser.add_argument("country", choices=["za"])
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--vertical", choices=available_verticals(), default="ict")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--as-of")
    search_parser.add_argument("--format", choices=["json"], default="json")
    search_parser.add_argument("--taxonomy-path", type=Path)

    evaluation_parser = commands.add_parser("evaluate")
    evaluation_parser.add_argument("country", choices=["za"])
    evaluation_parser.add_argument("--vertical", dest="verticals", choices=available_verticals(), nargs="+", default=available_verticals())

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("country", choices=["za", "ke"])

    documents_parser = commands.add_parser("documents")
    documents_subparsers = documents_parser.add_subparsers(dest="documents_action", required=True)
    documents_plan = documents_subparsers.add_parser("plan")
    documents_plan.add_argument("--input-parquet", type=Path, required=True)
    documents_plan.add_argument("--output-root", type=Path, required=True)
    documents_plan.add_argument("--source-run-id", required=True)
    documents_plan.add_argument("--source-snapshot-sha256", required=True)
    documents_plan.add_argument("--base-url", default="https://tenders.go.ke")
    documents_run = documents_subparsers.add_parser("run")
    documents_run.add_argument("--run-root", type=Path, required=True)
    documents_run.add_argument("--timeout", type=int, default=60)
    documents_run.add_argument("--rate", type=float, default=1.0)

    args = parser.parse_args()
    if args.command == "ingest":
        result = ingest(args.url or None, country=args.country, force=args.force, local_path=args.local_path)
    elif args.command == "normalize":
        result = normalize(args.source_path, country=args.country)
    elif args.command == "enrich":
        result = enrich(args.country)
    elif args.command == "enrich-source":
        result = compatibility_enrich_source(args.country, limit=args.limit)
    elif args.command == "source-enrich":
        if args.source_enrich_action == "plan":
            result = source_enrich_plan(args.country, limit=args.limit)
        elif args.source_enrich_action == "run":
            result = source_enrich_execute(args.run_id, country=args.country)
        elif args.source_enrich_action == "resume":
            result = source_enrich_resume(args.run_id, country=args.country)
        else:
            result = source_enrich_report(args.run_id, country=args.country)
    elif args.command in {"report", "profile"}:
        result = create_report(args.country)
    elif args.command == "materialize":
        result = materialize()
    elif args.command == "evaluate":
        result = evaluate_baselines(args.verticals)
    elif args.command == "verify":
        result = verify_outputs(args.country)
    elif args.command == "documents":
        if args.documents_action == "plan":
            result = document_plan(args.input_parquet, args.output_root, source_run_id=args.source_run_id, source_snapshot_sha256=args.source_snapshot_sha256, base_url=args.base_url)
        else:
            result = document_run(args.run_root, timeout=args.timeout, rate_per_second=args.rate)
    else:
        result = search(args.query, vertical=args.vertical, limit=args.limit, taxonomy_path=args.taxonomy_path, as_of=args.as_of)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
