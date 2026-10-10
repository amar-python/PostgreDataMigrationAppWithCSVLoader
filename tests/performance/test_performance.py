"""Performance tests — throughput, latency and resource bounds.

Budgets are deliberately generous so shared CI runners pass reliably while a
real regression (e.g. an accidental O(n²) loop or per-row round-trips) still
fails. Scale every budget with PERF_BUDGET_SCALE (default 1.0), e.g.
``PERF_BUDGET_SCALE=3 pytest tests/performance`` on a slow laptop.

The CPU-only cases need no database; the rest need a provisioned dev database
(PGDATABASE=te_mgmt_dev) and fail, never skip, without one.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from api.config import settings
from api.services.csv_parse import build_preview, cast_value, parse_csv, sanitize_columns

pytestmark = pytest.mark.performance

SCALE = float(os.environ.get("PERF_BUDGET_SCALE", "1.0"))


def _budget(seconds: float) -> float:
    return seconds * SCALE


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - start


def _csv(rows: int, tag: str = "") -> str:
    lines = ["id,name,amount,joined,active"]
    lines += [f"{i},name_{i}{tag},{i}.25,2024-01-{(i % 28) + 1:02d},{'true' if i % 2 else 'false'}"
              for i in range(rows)]
    return "\n".join(lines) + "\n"


# ── CPU-bound (no database) ───────────────────────────────────────────────────

class TestParserThroughput:
    def test_parse_100k_rows(self):
        """PERF-01 parse_csv handles 100,000 rows × 5 columns within 6s."""
        text = _csv(100_000)
        rows, elapsed = _timed(parse_csv, text)
        assert len(rows) == 100_001
        assert elapsed < _budget(6.0), f"parse_csv took {elapsed:.2f}s"

    def test_parse_scales_linearly(self):
        """PERF-02 10× the rows costs well under 30× the time (no quadratic blow-up)."""
        _, small = _timed(parse_csv, _csv(5_000))
        _, large = _timed(parse_csv, _csv(50_000))
        assert large < max(small, 0.01) * 30, f"5k={small:.3f}s 50k={large:.3f}s"

    def test_preview_of_large_file(self):
        """PERF-03 build_preview of a 50,000-row file returns within 4s."""
        out, elapsed = _timed(build_preview, _csv(50_000))
        assert out["status"] == "ok" and out["totalRowsApprox"] == 50_000
        assert elapsed < _budget(4.0), f"build_preview took {elapsed:.2f}s"

    def test_very_long_field(self):
        """PERF-04 a single 5 MB quoted field parses within 3s."""
        text = 'a\n"' + "x" * 5_000_000 + '"\n'
        rows, elapsed = _timed(parse_csv, text)
        assert len(rows[1][0]) == 5_000_000
        assert elapsed < _budget(3.0), f"long field took {elapsed:.2f}s"

    def test_sanitize_many_duplicate_headers(self):
        """PERF-05 sanitising 2,000 identical headers stays under 2s."""
        out, elapsed = _timed(sanitize_columns, ["col"] * 2_000)
        assert len(set(out)) == 2_000
        assert elapsed < _budget(2.0), f"sanitize_columns took {elapsed:.2f}s"

    def test_cast_200k_values(self):
        """PERF-06 casting 200,000 cells across all types completes within 3s."""
        samples = [("123", "int8"), ("1.5", "numeric"), ("yes", "boolean"),
                   ("2024-01-01", "date"), ("2024-01-01T00:00:00Z", "timestamptz"), ("x", "text")]
        start = time.perf_counter()
        for i in range(200_000):
            raw, t = samples[i % len(samples)]
            cast_value(raw, t)
        elapsed = time.perf_counter() - start
        assert elapsed < _budget(3.0), f"cast_value loop took {elapsed:.2f}s"


# ── End-to-end through the API (PostgreSQL) ───────────────────────────────────

def _post(client, cleanup, name, content, **extra):
    cleanup.append(name)
    start = time.perf_counter()
    r = client.post("/api/csv/upload", json={"fileName": name, "content": content, **extra})
    return r, time.perf_counter() - start


class TestUploadPerformance:
    def test_dynamic_upload_20k_rows(self, live_api, registry_cleanup, unique_tag):
        """PERF-07 a 20,000-row typed upload finishes within 20s with every row inserted."""
        r, elapsed = _post(live_api, registry_cleanup, f"perf_{unique_tag}.csv",
                           _csv(20_000, unique_tag),
                           types=["int8", "text", "numeric", "date", "boolean"])
        body = r.json()
        assert body["status"] == "ok", body.get("message")
        assert body["insertedRows"] == 20_000
        assert elapsed < _budget(20.0), f"20k-row upload took {elapsed:.2f}s"

    def test_all_failing_file_is_bounded(self, live_api, registry_cleanup, unique_tag):
        """PERF-08 a 20,000-row file where every row fails returns quickly and the
        response body stays small (rowErrors capped)."""
        content = "n\n" + "\n".join(f"bad_{i}_{unique_tag}" for i in range(20_000)) + "\n"
        r, elapsed = _post(live_api, registry_cleanup, f"perf_{unique_tag}.csv", content,
                           types=["int8"])
        body = r.json()
        assert body["failedRows"] == 20_000
        assert len(body["rowErrors"]) == settings.MAX_ROW_ERRORS_REPORTED
        assert len(r.content) < 200_000, f"response was {len(r.content)} bytes"
        assert elapsed < _budget(10.0), f"all-failing upload took {elapsed:.2f}s"

    def test_te_upload_1000_rows(self, live_api, registry_cleanup, te_org_cleanup, unique_tag):
        """PERF-09 a 1,000-row T&E upload uses the batch path and finishes within 10s."""
        names = [f"PERF_{unique_tag}_{i}" for i in range(1_000)]
        te_org_cleanup.extend(names)
        content = "name,org_type,country\n" + "\n".join(f"{n},academic,AU" for n in names) + "\n"
        r, elapsed = _post(live_api, registry_cleanup, f"perf_{unique_tag}.csv", content,
                           mode="te", targetTable="organisations")
        assert r.json()["insertedRows"] == 1_000
        assert elapsed < _budget(10.0), f"T&E upload took {elapsed:.2f}s"

    def test_concurrent_uploads(self, live_api, registry_cleanup, unique_tag):
        """PERF-10 8 concurrent uploads (pool size) all succeed within 30s."""
        jobs = [(f"perf_{unique_tag}_{i}.csv", _csv(2_000, f"{unique_tag}_{i}")) for i in range(8)]
        registry_cleanup.extend(name for name, _ in jobs)

        def send(job):
            name, content = job
            return live_api.post("/api/csv/upload", json={"fileName": name, "content": content}).json()

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(send, jobs))
        elapsed = time.perf_counter() - start
        assert [r["status"] for r in results] == ["ok"] * 8
        assert all(r["insertedRows"] == 2_000 for r in results)
        assert elapsed < _budget(30.0), f"8 concurrent uploads took {elapsed:.2f}s"


class TestReadLatency:
    @pytest.mark.parametrize("path", ["/api/health", "/api/csv/files", "/api/te/tables",
                                      "/api/audit/log"])
    def test_read_endpoint_p95_latency(self, live_api, path):
        """PERF-11 read endpoints answer with p95 latency under 500ms over 20 calls."""
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            assert live_api.get(path).status_code == 200
            timings.append(time.perf_counter() - start)
        p95 = sorted(timings)[int(len(timings) * 0.95) - 1]
        assert p95 < _budget(0.5), f"{path} p95={p95 * 1000:.0f}ms"

    def test_te_tables_uses_constant_queries(self, live_api, monkeypatch):
        """PERF-12 BUG-042: /api/te/tables issues 2 queries, not one per table."""
        from api.routers import te_routes

        executed = []

        class CountingCursor:
            """Wraps a real cursor and records every execute()."""

            def __init__(self, cur):
                self._cur = cur

            def __enter__(self):
                self._cur.__enter__()
                return self

            def __exit__(self, *exc):
                return self._cur.__exit__(*exc)

            def execute(self, query, *args, **kwargs):
                executed.append(query)
                return self._cur.execute(query, *args, **kwargs)

            def __getattr__(self, item):
                return getattr(self._cur, item)

        class CountingConn(te_routes.Conn):
            def __enter__(self):
                conn = super().__enter__()
                return type("ConnProxy", (), {"cursor": lambda _self: CountingCursor(conn.cursor())})()

        monkeypatch.setattr(te_routes, "Conn", CountingConn)
        assert live_api.get("/api/te/tables").status_code == 200
        assert len(executed) == 2, f"expected 2 queries, got {len(executed)}"

    def test_oversized_body_rejected_fast(self, live_api, monkeypatch):
        """PERF-13 a body over MAX_UPLOAD_BYTES is refused (413) in under 2s
        without parsing it."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1_000_000)
        start = time.perf_counter()
        r = live_api.post("/api/csv/upload", json={"fileName": "big.csv",
                                                   "content": "a\n" + "x" * 2_000_000})
        assert r.status_code == 413
        assert time.perf_counter() - start < _budget(2.0)
