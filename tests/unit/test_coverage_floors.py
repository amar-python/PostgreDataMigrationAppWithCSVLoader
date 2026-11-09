"""scripts/coverage_floors.py must fail closed (#194): below a floor, or missing."""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_spec = importlib.util.spec_from_file_location(
    "coverage_floors", Path(__file__).resolve().parents[2] / "scripts" / "coverage_floors.py")
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)


def _report(**pct):
    return {"files": {f"api/services/{n}.py": {"summary": {"percent_covered": v}} for n, v in pct.items()}}


def test_at_or_above_every_floor_passes():
    assert cf.check(_report(csv_parse=79.0, dynamic_loader=90, te_loader=96.2)) == []


def test_one_file_below_its_floor_fails_and_is_named():
    out = cf.check(_report(csv_parse=78.9, dynamic_loader=90, te_loader=99))
    assert len(out) == 1 and "csv_parse.py" in out[0] and "78.9%" in out[0]


def test_a_floored_file_missing_from_the_report_fails():
    out = cf.check(_report(csv_parse=99, dynamic_loader=99))
    assert len(out) == 1 and "te_loader.py" in out[0] and "not in the coverage report" in out[0]
