from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_baselines
from .materialize import materialize
from .normalize import normalize
from .report import create_report
from .retrieval import available_verticals
from .search import search
from .source import ingest
from .verification import verify_outputs


def main() -> None:
    parser = argparse.ArgumentParser(prog="pursuitmap")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("country", choices=["za"])
    ingest_parser.add_argument("--url")
    ingest_parser.add_argument("--local-path", type=Path)
    ingest_parser.add_argument("--force", action="store_true")

    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("country", choices=["za"])
    normalize_parser.add_argument("--source-path", type=Path)

    report_parser = commands.add_parser("report")
    report_parser.add_argument("country", choices=["za"])

    profile_parser = commands.add_parser("profile")
    profile_parser.add_argument("country", choices=["za"])

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
    verify_parser.add_argument("country", choices=["za"])

    args = parser.parse_args()
    if args.command == "ingest":
        result = ingest(args.url or None, force=args.force, local_path=args.local_path) if args.url else ingest(force=args.force, local_path=args.local_path)
    elif args.command == "normalize":
        result = normalize(args.source_path)
    elif args.command in {"report", "profile"}:
        result = create_report()
    elif args.command == "materialize":
        result = materialize()
    elif args.command == "evaluate":
        result = evaluate_baselines(args.verticals)
    elif args.command == "verify":
        result = verify_outputs()
    else:
        result = search(args.query, vertical=args.vertical, limit=args.limit, taxonomy_path=args.taxonomy_path, as_of=args.as_of)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
