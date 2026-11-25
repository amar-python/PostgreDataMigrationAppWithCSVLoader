"""Reporting and structured logging.

Each migration run produces:
  * A timestamped log file under `reports/logs/<run_id>.log`
  * A per-job JSON result file under `reports/<run_id>/<job_name>.json`
  * A run-level summary `reports/<run_id>/summary.json`
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


REPORT_DIR = Path(os.getenv("REPORT_DIR", "./reports"))
MAX_REPORT_RUNS = int(os.getenv("MAX_REPORT_RUNS", "5"))


@dataclass
class CheckResult:
    """A single named check inside a stage."""
    name: str
    passed: bool
    detail: str = ""
    metric: Optional[Dict[str, Any]] = None


@dataclass
class StageResult:
    """One stage of the validation pipeline (e.g. pre_import, schema, integrity)."""
    stage: str
    passed: bool = True
    checks: List[CheckResult] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str = "",
               metric: Optional[Dict[str, Any]] = None) -> CheckResult:
        result = CheckResult(name=name, passed=passed, detail=detail, metric=metric)
        self.checks.append(result)
        if not passed:
            self.passed = False
        return result


@dataclass
class JobReport:
    job_name: str
    started_at: str
    finished_at: Optional[str] = None
    success: bool = False
    stages: List[StageResult] = field(default_factory=list)
    rows_in_csv: int = 0
    rows_in_staging: int = 0
    rows_in_target: int = 0
    error: Optional[str] = None

    def add_stage(self, stage: StageResult) -> None:
        self.stages.append(stage)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_name": self.job_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "success": self.success,
            "rows_in_csv": self.rows_in_csv,
            "rows_in_staging": self.rows_in_staging,
            "rows_in_target": self.rows_in_target,
            "error": self.error,
            "stages": [
                {
                    "stage": s.stage,
                    "passed": s.passed,
                    "checks": [asdict(c) for c in s.checks],
                }
                for s in self.stages
            ],
        }


class Reporter:
    """Top-level reporting facade for a migration run."""

    def __init__(self, run_id: Optional[str] = None) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        ) + "-" + uuid.uuid4().hex[:6]
        self.run_dir = REPORT_DIR / self.run_id
        self.log_dir = REPORT_DIR / "logs"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.logger = self._setup_logger()
        self.job_reports: List[JobReport] = []

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"migrator.{self.run_id}")
        logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
        # Avoid duplicate handlers on re-instantiation
        logger.handlers.clear()

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.FileHandler(self.log_dir / f"{self.run_id}.log")
        file_handler.setFormatter(fmt)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)

        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        logger.propagate = False
        return logger

    def new_job(self, job_name: str) -> JobReport:
        report = JobReport(
            job_name=job_name,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.job_reports.append(report)
        return report

    def finalize_job(self, report: JobReport) -> None:
        report.finished_at = datetime.now(timezone.utc).isoformat()
        report.success = all(s.passed for s in report.stages) and report.error is None

        out = self.run_dir / f"{report.job_name}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        self.logger.info(
            "Job %s finished: success=%s, report=%s",
            report.job_name, report.success, out,
        )

    def write_summary(self) -> Path:
        summary = {
            "run_id": self.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_jobs": len(self.job_reports),
            "successful_jobs": sum(1 for r in self.job_reports if r.success),
            "failed_jobs": sum(1 for r in self.job_reports if not r.success),
            "jobs": [r.to_dict() for r in self.job_reports],
        }
        out = self.run_dir / "summary.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        self._prune_old_runs()
        return out

    def _prune_old_runs(self) -> None:
        """Keep only the most recent MAX_REPORT_RUNS report directories and logs."""
        run_pattern = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")
        run_dirs = sorted(
            d for d in REPORT_DIR.iterdir()
            if d.is_dir() and run_pattern.match(d.name)
        )
        if len(run_dirs) <= MAX_REPORT_RUNS:
            return
        for old_dir in run_dirs[:-MAX_REPORT_RUNS]:
            old_log = self.log_dir / f"{old_dir.name}.log"
            shutil.rmtree(old_dir, ignore_errors=True)
            if old_log.exists():
                old_log.unlink(missing_ok=True)
            self.logger.info("Pruned old report run: %s", old_dir.name)
