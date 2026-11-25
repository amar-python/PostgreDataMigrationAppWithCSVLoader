"""CLI entry point for the migration framework.

Usage:
    python main.py migrate                  # run every configured job
    python main.py migrate --job users      # run a single named job
    python main.py migrate --dry-run        # validate but don't promote
    python main.py watch --dir ./incoming   # watch a directory for CSVs
"""
from __future__ import annotations

import argparse
import sys

from src.config import load_db_config, load_jobs
from src.migrator import run_all, run_job
from src.reporting import Reporter
from src.watcher import watch


def cmd_migrate(args: argparse.Namespace) -> int:
    db = load_db_config()

    if args.job:
        jobs = [j for j in load_jobs(args.config) if j.name == args.job]
        if not jobs:
            print(f"No job named '{args.job}' in {args.config}", file=sys.stderr)
            return 2
        reporter = Reporter()
        ok = run_job(jobs[0], db, reporter, promote=not args.dry_run)
        reporter.write_summary()
        return 0 if ok else 1

    reporter = run_all(promote=not args.dry_run, config_path=args.config)
    failed = sum(1 for r in reporter.job_reports if not r.success)
    return 0 if failed == 0 else 1


def cmd_watch(args: argparse.Namespace) -> int:
    watch(args.dir, config_path=args.config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="migrator")
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    sub = p.add_subparsers(dest="command", required=True)

    pm = sub.add_parser("migrate", help="Run one or more migration jobs")
    pm.add_argument("--job", help="Run only a single named job")
    pm.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and load to staging but do not promote to target",
    )
    pm.set_defaults(func=cmd_migrate)

    pw = sub.add_parser("watch", help="Watch a directory for incoming CSVs")
    pw.add_argument("--dir", required=True, help="Directory to watch")
    pw.set_defaults(func=cmd_watch)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
