# scripts/run_qa.ps1 — Windows equivalent of the Makefile QA targets.
#
# Usage:
#   .\scripts\run_qa.ps1 test-free
#   .\scripts\run_qa.ps1 test-gate
#   .\scripts\run_qa.ps1 test-evals
#   .\scripts\run_qa.ps1 test-e2e
#   .\scripts\run_qa.ps1 test-all
#   .\scripts\run_qa.ps1 lint
#   .\scripts\run_qa.ps1 health
#   .\scripts\run_qa.ps1 eval-list
#   .\scripts\run_qa.ps1 eval-compare
#   .\scripts\run_qa.ps1 eval-summary
#   .\scripts\run_qa.ps1 select-tests
param(
    [Parameter(Position = 0)]
    [string]$Target = "test-free"
)

$ErrorActionPreference = "Stop"

switch ($Target) {
    "test-free" {
        pytest -m "unit or regression or security or snapshot" tests/ -v
    }
    "test-gate" {
        pytest -m "unit or regression or security or snapshot" tests/ `
            --cov=build/csv --cov=evals --cov-report=term-missing
    }
    "test-evals" {
        python evals/runner.py --tiers p,i,s --verbose
    }
    "test-e2e" {
        pytest -m "e2e or integration or parity" tests/ -v
    }
    "test-all" {
        pytest tests/ --cov=build/csv --cov=evals --cov-report=term-missing
        python evals/runner.py --tiers p,i,s --verbose
    }
    "lint" {
        $pyFiles = @(
            "build/csv/validator.py",
            "evals/runner.py",
            "evals/gap_report.py",
            "tests/test_csv_validator.py",
            "tests/test_evals_runner.py"
        )
        $scriptPy = Get-ChildItem scripts/*.py -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName }
        $allFiles = $pyFiles + $scriptPy
        Write-Host "=== flake8 ===" -ForegroundColor Yellow
        python -m flake8 $allFiles --max-line-length=120
        Write-Host "=== bandit (security) ===" -ForegroundColor Yellow
        python -m bandit $pyFiles -ll -q
    }
    "lint-diff" {
        python scripts/select_tests.py --lint-diff
    }
    "health" {
        python scripts/health_check.py
    }
    "eval-list" {
        python scripts/eval_list.py
    }
    "eval-compare" {
        python scripts/eval_compare.py
    }
    "eval-summary" {
        python scripts/eval_summary.py
    }
    "select-tests" {
        python scripts/select_tests.py
    }
    default {
        Write-Host "Unknown target: $Target" -ForegroundColor Red
        Write-Host "Valid targets: test-free, test-gate, test-evals, test-e2e, test-all, lint, lint-diff, health, eval-list, eval-compare, eval-summary, select-tests"
        exit 1
    }
}
