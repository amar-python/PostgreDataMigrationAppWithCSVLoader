"""#330: no function in api/services/ is longer than 80 lines.

The loaders' main functions had grown to 277 and 263 lines, mixing validation, permission checks, casting, inserts with
savepoints, registry writes and result shaping. Each fix inside them needed a full system test, because no piece could
be tested alone. Split a function that reaches the limit rather than raising it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 80


def _long_functions(path: Path, root: Path = ROOT) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            length = node.end_lineno - start + 1
            if length > LIMIT:
                found.append(f"{path.relative_to(root)}:{node.lineno} {node.name} ({length} lines)")
    return found


def test_no_service_function_is_over_the_limit():
    files = sorted((ROOT / "api" / "services").glob("*.py"))
    assert len(files) >= 10, "api/services/ looks empty; this check would pass over nothing"
    long = [f for path in files for f in _long_functions(path)]
    assert not long, f"over {LIMIT} lines:\n  " + "\n  ".join(long)


def test_the_check_finds_a_long_function_and_counts_its_decorators(tmp_path):
    probe = tmp_path / "probe.py"
    body = "    x = 1\n" * (LIMIT - 1)
    probe.write_text("def at_limit():\n" + body + "\n\n@staticmethod\ndef over():\n" + body, encoding="utf-8")
    assert _long_functions(probe, tmp_path) == [f"probe.py:{LIMIT + 4} over ({LIMIT + 1} lines)"]
