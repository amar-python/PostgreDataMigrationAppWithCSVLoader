"""The sample data in input_data/ must stay synthetic: this repository is public.

Every file under input_data/ is made-up data in the shape of the real files the tool was written against. A real export
(customer or participant records) must never be committed here. The guard is deliberately simple: any e-mail address in
a sample must be at an ``example.*`` domain, and nothing in input_data/ may be a file type other than the known samples.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

INPUT = Path(__file__).resolve().parents[1] / "input_data"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)")
ALLOWED_SUFFIXES = {".csv", ".tsv", ".sql"}


def _sample_files() -> list[Path]:
    return sorted(p for p in INPUT.rglob("*") if p.is_file())


def test_there_are_samples_to_check():
    assert len(_sample_files()) >= 10, "input_data/ lost its sample files, so this guard would pass on nothing"


def test_only_known_sample_file_types_are_present():
    odd = [p.name for p in _sample_files() if p.suffix not in ALLOWED_SUFFIXES]
    assert not odd, f"unexpected files in input_data/ (spreadsheets, exports, dumps?): {odd}"


def test_every_email_address_in_the_samples_is_at_an_example_domain():
    real_looking = []
    for path in _sample_files():
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for match in EMAIL.finditer(text):
            if not match.group(1).lower().startswith("example."):
                real_looking.append((path.name, match.group(0)))
    assert not real_looking, f"e-mail addresses that are not at an example.* domain: {real_looking[:5]}"
