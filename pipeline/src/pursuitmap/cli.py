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
from .durable_source_enrichment import status as source_enrich_status
from .durable_source_enrichment import supervise as source_enrich_supervise
from .durable_source_enrichment import retry_failed as source_enrich_retry_failed
from .verification import verify_outputs
from .document_download import plan as document_plan
from .document_download import run as document_run
from .document_extraction import parse_run as document_parse
from .document_features import extract_features, report as document_feature_report
from .document_analysis import analyze_classification, compare_classifications
from .source_enrichment_benchmark import benchmark as source_enrich_benchmark
from .mapping_discovery import execute as gap_execute
from .mapping_discovery import partition_plan, partition_report
from .mapping_discovery import plan as gap_plan
from .mapping_discovery import report as gap_report
from .mapping_discovery import promote as gap_promote
from .mapping_discovery import combine as gap_combine
from .enrichment_profile import profile as source_enrich_profile
from .enrichment_analysis import analyze as source_enrich_analyze
from .contract_export import capture as contract_export_capture
from .network_preflight import check as network_check
from .sa_api_enrichment import plan as sa_api_plan, run as sa_api_run, report as sa_api_report
from .sa_api_bulk import plan as sa_bulk_plan, run as sa_bulk_run, report as sa_bulk_report
from .sa_api_supervisor import plan as sa_supervise_plan, run as sa_supervise_run, report as sa_supervise_report, status as sa_supervise_status, flush_permanent_failures as sa_supervise_flush
from .sa_api_probe import plan as sa_probe_plan, run as sa_probe_run, report as sa_probe_report, status as sa_probe_status
from .watch import watch


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

    network_parser = commands.add_parser("network-check")
    network_parser.add_argument("--url", default="https://tenders.go.ke")

    watch_parser = commands.add_parser("watch", help="watch a run progress sidecar")
    watch_parser.add_argument("--run-root", type=Path)
    watch_parser.add_argument("--search-root", type=Path, default=Path("data/enriched"))
    watch_parser.add_argument("--interval", type=int, default=10)
    watch_parser.add_argument("--once", action="store_true")

    sa_api_parser = commands.add_parser("sa-api-enrich")
    sa_api_subparsers = sa_api_parser.add_subparsers(dest="sa_api_action", required=True)
    sa_api_plan_parser = sa_api_subparsers.add_parser("plan")
    sa_api_plan_parser.add_argument("--limit", type=int, default=25)
    sa_api_run_parser = sa_api_subparsers.add_parser("run")
    sa_api_run_parser.add_argument("--run-id", required=True)
    sa_api_run_parser.add_argument("--rate", type=float, default=1.0)
    sa_api_run_parser.add_argument("--timeout", type=int, default=30)
    sa_api_report_parser = sa_api_subparsers.add_parser("report")
    sa_api_report_parser.add_argument("--run-id", required=True)

    sa_bulk_parser = commands.add_parser("sa-api-bulk")
    sa_bulk_subparsers = sa_bulk_parser.add_subparsers(dest="sa_bulk_action", required=True)
    sa_bulk_subparsers.add_parser("plan")
    sa_bulk_run_parser = sa_bulk_subparsers.add_parser("run")
    sa_bulk_run_parser.add_argument("--run-id", required=True)
    sa_bulk_run_parser.add_argument("--rate", type=float, default=1.0)
    sa_bulk_run_parser.add_argument("--timeout", type=int, default=90)
    sa_bulk_report_parser = sa_bulk_subparsers.add_parser("report")
    sa_bulk_report_parser.add_argument("--run-id", required=True)

    sa_probe_parser = commands.add_parser("sa-api-probe")
    sa_probe_subparsers = sa_probe_parser.add_subparsers(dest="sa_probe_action", required=True)
    sa_probe_plan_parser = sa_probe_subparsers.add_parser("plan")
    sa_probe_plan_parser.add_argument("--parent-run-id", required=True)
    sa_probe_run_parser = sa_probe_subparsers.add_parser("run")
    sa_probe_run_parser.add_argument("--run-id", required=True)
    sa_probe_run_parser.add_argument("--timeout", type=int, default=90)
    for action in ("status", "report"):
        reader = sa_probe_subparsers.add_parser(action)
        reader.add_argument("--run-id", required=True)

    sa_supervise_parser = commands.add_parser("sa-api-supervise")
    sa_supervise_subparsers = sa_supervise_parser.add_subparsers(dest="sa_supervise_action", required=True)
    sa_supervise_plan_parser = sa_supervise_subparsers.add_parser("plan")
    sa_supervise_plan_parser.add_argument("--parent-run-id", required=True)
    for action in ("run", "resume"):
        runner = sa_supervise_subparsers.add_parser(action)
        runner.add_argument("--run-id", required=True)
        runner.add_argument("--rate", type=float, default=1.0)
        runner.add_argument("--timeout", type=int, default=90)
        runner.add_argument("--max-concurrency", type=int, default=4)
    for action in ("status", "report"):
        reader = sa_supervise_subparsers.add_parser(action)
        reader.add_argument("--run-id", required=True)
    sa_supervise_flush_parser = sa_supervise_subparsers.add_parser("flush")
    sa_supervise_flush_parser.add_argument("--run-id", required=True)
    sa_supervise_flush_parser.add_argument("--reason", action="append", default=[])

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
    durable_run.add_argument("--workers", type=int)
    durable_resume = durable_subparsers.add_parser("resume")
    durable_resume.add_argument("country", choices=["ke"])
    durable_resume.add_argument("--run-id", required=True)
    durable_resume.add_argument("--workers", type=int)
    durable_report = durable_subparsers.add_parser("report")
    durable_report.add_argument("country", choices=["ke"])
    durable_report.add_argument("--run-id", required=True)
    durable_status = durable_subparsers.add_parser("status")
    durable_status.add_argument("country", choices=["ke"])
    durable_status.add_argument("--run-id", required=True)
    durable_supervise = durable_subparsers.add_parser("supervise")
    durable_supervise.add_argument("country", choices=["ke"])
    durable_supervise.add_argument("--run-id", required=True)
    durable_supervise.add_argument("--workers", type=int)
    durable_supervise.add_argument("--max-cycles", type=int, default=100)
    durable_supervise.add_argument("--max-runtime-hours", type=float, default=24.0)
    durable_profile = durable_subparsers.add_parser("profile")
    durable_profile.add_argument("country", choices=["ke"])
    durable_profile.add_argument("--run-id", required=True)
    durable_retry = durable_subparsers.add_parser("retry-failed")
    durable_retry.add_argument("country", choices=["ke"])
    durable_retry.add_argument("--run-id", required=True)
    durable_retry.add_argument("--job-type", choices=["list", "detail"])
    durable_analyze = durable_subparsers.add_parser("analyze")
    durable_analyze.add_argument("country", choices=["ke"])
    durable_analyze.add_argument("--run-id", required=True)
    durable_benchmark = durable_subparsers.add_parser("benchmark")
    durable_benchmark.add_argument("country", choices=["ke"])
    durable_benchmark.add_argument("--run-id", required=True)
    durable_benchmark.add_argument("--sample-per-level", type=int, default=20)
    durable_benchmark.add_argument("--rates", type=float, nargs="+", default=[2.0, 3.0])
    durable_benchmark.add_argument("--workers", type=int, nargs="+", default=[2, 3])
    gap_plan_parser = durable_subparsers.add_parser("gap-plan")
    gap_plan_parser.add_argument("country", choices=["ke"])
    gap_plan_parser.add_argument("--source-run-id", required=True)
    gap_plan_parser.add_argument("--from-year", type=int, default=2018)
    gap_plan_parser.add_argument("--to-year", type=int, default=2025)
    gap_plan_parser.add_argument("--max-jobs", type=int, default=250)
    gap_plan_parser.add_argument("--contract-only", action="store_true")
    gap_plan_parser.add_argument("--financial-year-json", action="store_true")
    gap_plan_parser.add_argument("--financial-year-json-resume-run")
    gap_run_parser = durable_subparsers.add_parser("gap-run")
    gap_run_parser.add_argument("country", choices=["ke"])
    gap_run_parser.add_argument("--run-id", required=True)
    gap_resume_parser = durable_subparsers.add_parser("gap-resume")
    gap_resume_parser.add_argument("country", choices=["ke"])
    gap_resume_parser.add_argument("--run-id", required=True)
    gap_report_parser = durable_subparsers.add_parser("gap-report")
    gap_report_parser.add_argument("country", choices=["ke"])
    gap_report_parser.add_argument("--run-id", required=True)
    partition_plan_parser = durable_subparsers.add_parser("partition-plan")
    partition_plan_parser.add_argument("country", choices=["ke"])
    partition_plan_parser.add_argument("--source-run-id", required=True)
    partition_plan_parser.add_argument("--from-year", type=int, default=2018)
    partition_plan_parser.add_argument("--to-year", type=int, default=2025)
    partition_plan_parser.add_argument("--max-requests", type=int, default=250)
    partition_run_parser = durable_subparsers.add_parser("partition-run")
    partition_run_parser.add_argument("country", choices=["ke"])
    partition_run_parser.add_argument("--run-id", required=True)
    partition_resume_parser = durable_subparsers.add_parser("partition-resume")
    partition_resume_parser.add_argument("country", choices=["ke"])
    partition_resume_parser.add_argument("--run-id", required=True)
    partition_report_parser = durable_subparsers.add_parser("partition-report")
    partition_report_parser.add_argument("country", choices=["ke"])
    partition_report_parser.add_argument("--run-id", required=True)
    promote_parser = durable_subparsers.add_parser("promote")
    promote_parser.add_argument("country", choices=["ke"])
    promote_parser.add_argument("--discovery-run-id", required=True)
    promote_parser.add_argument("--sample-per-cohort", type=int, default=100)
    promote_parser.add_argument("--all", dest="all_mappings", action="store_true")
    combine_parser = durable_subparsers.add_parser("combine")
    combine_parser.add_argument("country", choices=["ke"])
    combine_parser.add_argument("--child-run-id", required=True)
    combine_parser.add_argument("--baseline-run-id")
    combine_parser.add_argument("--additional-child-run-id", action="append", default=[])
    export_parser = durable_subparsers.add_parser("contract-export")
    export_parser.add_argument("country", choices=["ke"])

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
    documents_run.add_argument("--limit", type=int)
    documents_parse = documents_subparsers.add_parser("parse")
    documents_parse.add_argument("--run-root", type=Path, required=True)
    documents_parse.add_argument("--limit", type=int)
    documents_parse.add_argument("--skip-hash", action="append", default=[])
    documents_parse.add_argument("--ocr", action="store_true")
    documents_extract = documents_subparsers.add_parser("extract")
    documents_extract.add_argument("--run-root", type=Path, required=True)
    documents_extract.add_argument("--rules-path", type=Path, required=True)
    documents_analysis = documents_subparsers.add_parser("classify-analyze")
    documents_analysis.add_argument("--run-root", type=Path, required=True)
    documents_analysis.add_argument("--classification-dir", type=Path, required=True)
    documents_analysis.add_argument("--threshold", type=float, default=0.45)
    documents_compare = documents_subparsers.add_parser("classify-compare")
    documents_compare.add_argument("--left-dir", type=Path, required=True)
    documents_compare.add_argument("--right-dir", type=Path, required=True)
    documents_compare.add_argument("--output-path", type=Path, required=True)
    documents_report = documents_subparsers.add_parser("report")
    documents_report.add_argument("--run-root", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "network-check":
        print(json.dumps(network_check(args.url), indent=2))
        return
    if args.command == "watch":
        watch(args.run_root, search_root=args.search_root, interval=args.interval, once=args.once)
        return
    if args.command == "sa-api-enrich":
        network_check("https://ocds-api.etenders.gov.za") if args.sa_api_action == "run" else None
        if args.sa_api_action == "plan":
            result = sa_api_plan(limit=args.limit)
        elif args.sa_api_action == "run":
            result = sa_api_run(args.run_id, rate=args.rate, timeout=args.timeout)
        else:
            result = sa_api_report(args.run_id)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "sa-api-bulk":
        network_check("https://ocds-api.etenders.gov.za") if args.sa_bulk_action == "run" else None
        if args.sa_bulk_action == "plan":
            result = sa_bulk_plan()
        elif args.sa_bulk_action == "run":
            result = sa_bulk_run(args.run_id, rate=args.rate, timeout=args.timeout)
        else:
            result = sa_bulk_report(args.run_id)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "sa-api-supervise":
        network_check("https://ocds-api.etenders.gov.za") if args.sa_supervise_action in {"run", "resume"} else None
        if args.sa_supervise_action == "plan":
            result = sa_supervise_plan(args.parent_run_id)
        elif args.sa_supervise_action in {"run", "resume"}:
            result = sa_supervise_run(args.run_id, rate=args.rate, timeout=args.timeout, max_concurrency=args.max_concurrency)
        elif args.sa_supervise_action == "status":
            result = sa_supervise_status(args.run_id)
        elif args.sa_supervise_action == "flush":
            result = sa_supervise_flush(args.run_id, reasons=tuple(args.reason))
        else:
            result = sa_supervise_report(args.run_id)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "sa-api-probe":
        network_check("https://ocds-api.etenders.gov.za") if args.sa_probe_action == "run" else None
        if args.sa_probe_action == "plan":
            result = sa_probe_plan(args.parent_run_id)
        elif args.sa_probe_action == "run":
            result = sa_probe_run(args.run_id, timeout=args.timeout)
        elif args.sa_probe_action == "status":
            result = sa_probe_status(args.run_id)
        else:
            result = sa_probe_report(args.run_id)
        print(json.dumps(result, indent=2, default=str))
        return
    live_source_actions = {"run", "resume", "gap-run", "gap-resume", "partition-run", "partition-resume", "supervise"}
    if args.command == "enrich-source" or args.command == "documents" and args.documents_action == "run" or args.command == "source-enrich" and args.source_enrich_action in live_source_actions or args.command == "source-enrich" and args.source_enrich_action == "contract-export":
        network_check()
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
            result = source_enrich_execute(args.run_id, country=args.country, workers=args.workers)
        elif args.source_enrich_action == "resume":
            result = source_enrich_resume(args.run_id, country=args.country, workers=args.workers)
        elif args.source_enrich_action == "benchmark":
            if len(args.rates) != len(args.workers):
                parser.error("--rates and --workers must have the same length")
            result = source_enrich_benchmark(args.run_id, country=args.country, sample_per_level=args.sample_per_level, rates=tuple(args.rates), concurrency=tuple(args.workers))
        elif args.source_enrich_action == "status":
            result = source_enrich_status(args.run_id, country=args.country)
        elif args.source_enrich_action == "supervise":
            result = source_enrich_supervise(args.run_id, country=args.country, workers=args.workers, max_cycles=args.max_cycles, max_runtime_seconds=args.max_runtime_hours * 60 * 60)
        elif args.source_enrich_action == "profile":
            result = source_enrich_profile(args.run_id, country=args.country)
        elif args.source_enrich_action == "retry-failed":
            result = source_enrich_retry_failed(args.run_id, country=args.country, job_type=args.job_type)
        elif args.source_enrich_action == "analyze":
            result = source_enrich_analyze(args.run_id, country=args.country)
        elif args.source_enrich_action == "gap-plan":
            result = gap_plan(args.source_run_id, country=args.country, from_year=args.from_year, to_year=args.to_year, max_jobs=args.max_jobs, contract_only=args.contract_only, financial_year_json_only=args.financial_year_json, financial_year_json_resume_run=args.financial_year_json_resume_run)
        elif args.source_enrich_action == "gap-run":
            result = gap_execute(args.run_id, country=args.country)
        elif args.source_enrich_action == "gap-resume":
            result = gap_execute(args.run_id, country=args.country, reset_failures=True)
        elif args.source_enrich_action == "gap-report":
            result = gap_report(args.run_id, country=args.country)
        elif args.source_enrich_action == "partition-plan":
            result = partition_plan(args.source_run_id, country=args.country, from_year=args.from_year, to_year=args.to_year, max_requests=args.max_requests)
        elif args.source_enrich_action == "partition-run":
            result = gap_execute(args.run_id, country=args.country)
        elif args.source_enrich_action == "partition-resume":
            result = gap_execute(args.run_id, country=args.country, reset_failures=True)
        elif args.source_enrich_action == "partition-report":
            result = partition_report(args.run_id, country=args.country)
        elif args.source_enrich_action == "promote":
            result = gap_promote(args.discovery_run_id, country=args.country, sample_per_cohort=args.sample_per_cohort, all_mappings=args.all_mappings)
        elif args.source_enrich_action == "combine":
            result = gap_combine(args.child_run_id, country=args.country, baseline_run=args.baseline_run_id, additional_child_runs=tuple(args.additional_child_run_id))
        elif args.source_enrich_action == "contract-export":
            result = contract_export_capture(args.country)
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
        elif args.documents_action == "run":
            result = document_run(args.run_root, timeout=args.timeout, rate_per_second=args.rate, limit=args.limit)
        elif args.documents_action == "parse":
            result = document_parse(args.run_root, limit=args.limit, skip_hashes=tuple(args.skip_hash), enable_ocr=args.ocr)
        elif args.documents_action == "extract":
            result = extract_features(args.run_root, args.rules_path)
        elif args.documents_action == "classify-analyze":
            result = analyze_classification(args.run_root, args.classification_dir, threshold=args.threshold)
        elif args.documents_action == "classify-compare":
            result = compare_classifications(args.left_dir, args.right_dir, args.output_path)
        else:
            result = document_feature_report(args.run_root)
    else:
        result = search(args.query, vertical=args.vertical, limit=args.limit, taxonomy_path=args.taxonomy_path, as_of=args.as_of)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
