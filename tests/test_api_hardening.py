"""Tests for the O-03 (auth fail-closed, rate limiting) and O-04 (audit) work.

All tests here are `unit`: no database, no network. The rate limiter is exercised
directly where possible and through the middleware where the HTTP contract
matters (status code, Retry-After header, exempt paths).
"""

from __future__ import annotations

import unittest

import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app, assert_auth_configured
from api.ratelimit import SlidingWindowLimiter, limiter
from api.services.audit import VALID_ACTIONS, coerce_file_id, write_audit

client = TestClient(app)


@pytest.mark.unit
class AuthFailsClosed(unittest.TestCase):
    """O-03: a deployed environment must not boot without an API key."""

    def test_dev_may_run_without_a_key(self):
        # The local workflow must keep working — this is why the gate keys on
        # API_ENV rather than simply requiring a key everywhere.
        assert_auth_configured("dev", "")

    def test_any_key_is_accepted_in_dev(self):
        assert_auth_configured("dev", "s3cret")

    def test_prod_without_a_key_refuses_to_start(self):
        with self.assertRaises(RuntimeError) as ctx:
            assert_auth_configured("prod", "")
        # The message must name both the cause and the two ways out, because it
        # surfaces in a container log where nobody can ask a follow-up question.
        msg = str(ctx.exception)
        self.assertIn("API_KEY", msg)
        self.assertIn("prod", msg)
        self.assertIn("API_ENV=dev", msg)

    def test_staging_and_test_also_refuse(self):
        for env in ("test", "staging", "production", "azure"):
            with self.subTest(env=env):
                with self.assertRaises(RuntimeError):
                    assert_auth_configured(env, "")

    def test_deployed_env_with_a_key_starts(self):
        assert_auth_configured("prod", "a-real-key")


@pytest.mark.unit
class RateLimiterAlgorithm(unittest.TestCase):
    """O-03: the sliding window itself, driven with an injected clock."""

    def setUp(self):
        self.lim = SlidingWindowLimiter()

    def test_requests_under_budget_are_allowed(self):
        for i in range(5):
            allowed, retry = self.lim.check("c", "read", 5, 60.0, now=100.0 + i)
            self.assertTrue(allowed, f"request {i} should be allowed")
            self.assertEqual(retry, 0.0)

    def test_request_over_budget_is_refused(self):
        for i in range(3):
            self.lim.check("c", "read", 3, 60.0, now=100.0 + i)
        allowed, retry = self.lim.check("c", "read", 3, 60.0, now=103.0)
        self.assertFalse(allowed)
        self.assertGreater(retry, 0.0)

    def test_retry_after_points_at_the_oldest_hit_leaving_the_window(self):
        # Oldest hit at t=100 with a 60s window frees a slot at t=160.
        for i in range(2):
            self.lim.check("c", "read", 2, 60.0, now=100.0 + i)
        _, retry = self.lim.check("c", "read", 2, 60.0, now=110.0)
        self.assertAlmostEqual(retry, 50.0, places=6)

    def test_window_expiry_frees_the_budget(self):
        for i in range(2):
            self.lim.check("c", "read", 2, 60.0, now=100.0 + i)
        blocked, _ = self.lim.check("c", "read", 2, 60.0, now=120.0)
        self.assertFalse(blocked)
        # Past t=161 both original hits have aged out.
        allowed, _ = self.lim.check("c", "read", 2, 60.0, now=162.0)
        self.assertTrue(allowed)

    def test_zero_budget_disables_the_limit(self):
        for i in range(50):
            allowed, _ = self.lim.check("c", "read", 0, 60.0, now=100.0 + i)
            self.assertTrue(allowed)

    def test_read_and_write_scopes_are_independent(self):
        for i in range(2):
            self.lim.check("c", "write", 2, 60.0, now=100.0 + i)
        refused, _ = self.lim.check("c", "write", 2, 60.0, now=102.0)
        self.assertFalse(refused)
        # A spent write budget must not block reads.
        allowed, _ = self.lim.check("c", "read", 2, 60.0, now=102.0)
        self.assertTrue(allowed)

    def test_clients_are_independent(self):
        for i in range(2):
            self.lim.check("noisy", "read", 2, 60.0, now=100.0 + i)
        refused, _ = self.lim.check("noisy", "read", 2, 60.0, now=102.0)
        self.assertFalse(refused)
        allowed, _ = self.lim.check("quiet", "read", 2, 60.0, now=102.0)
        self.assertTrue(allowed, "one client's traffic must not limit another's")

    def test_bucket_table_is_bounded(self):
        # A spray of spoofed identities must not grow memory without limit.
        from api.ratelimit import _MAX_TRACKED_CLIENTS
        for i in range(_MAX_TRACKED_CLIENTS + 250):
            self.lim.check(f"client-{i}", "read", 5, 60.0, now=100.0)
        self.assertLessEqual(len(self.lim._buckets), _MAX_TRACKED_CLIENTS)

    def test_reset_clears_state(self):
        self.lim.check("c", "read", 1, 60.0, now=100.0)
        refused, _ = self.lim.check("c", "read", 1, 60.0, now=101.0)
        self.assertFalse(refused)
        self.lim.reset()
        allowed, _ = self.lim.check("c", "read", 1, 60.0, now=102.0)
        self.assertTrue(allowed)


@pytest.mark.unit
class RateLimitMiddleware(unittest.TestCase):
    """O-03: the HTTP contract the frontend and any gateway will see."""

    def setUp(self):
        limiter.reset()
        self._saved = (
            settings.RATE_LIMIT_READS_PER_MINUTE,
            settings.RATE_LIMIT_WRITES_PER_MINUTE,
        )

    def tearDown(self):
        (settings.RATE_LIMIT_READS_PER_MINUTE,
         settings.RATE_LIMIT_WRITES_PER_MINUTE) = self._saved
        limiter.reset()

    def test_exceeding_the_write_budget_returns_429_with_retry_after(self):
        settings.RATE_LIMIT_WRITES_PER_MINUTE = 2
        payload = {"fileName": "x.csv", "content": "a,b\n1,2\n"}
        # The budget counts requests, not successes: a 422/500 still consumes a
        # slot, which is the point — it is the work that needs bounding.
        for _ in range(2):
            client.post("/api/csv/preview", json=payload)
        resp = client.post("/api/csv/preview", json=payload)
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)
        # Retry-After: 0 would tell the client to retry instantly.
        self.assertGreaterEqual(int(resp.headers["Retry-After"]), 1)

    def test_health_is_never_rate_limited(self):
        settings.RATE_LIMIT_READS_PER_MINUTE = 1
        # An uptime probe polls constantly; throttling it would create false alarms.
        for _ in range(5):
            self.assertNotEqual(client.get("/api/health").status_code, 429)

    def test_openapi_is_never_rate_limited(self):
        settings.RATE_LIMIT_READS_PER_MINUTE = 1
        for _ in range(4):
            self.assertNotEqual(client.get("/openapi.json").status_code, 429)

    def test_disabled_budget_allows_everything(self):
        settings.RATE_LIMIT_WRITES_PER_MINUTE = 0
        payload = {"fileName": "x.csv", "content": "a,b\n1,2\n"}
        for _ in range(25):
            self.assertNotEqual(
                client.post("/api/csv/preview", json=payload).status_code, 429
            )

    def test_forwarded_for_cannot_be_used_to_evade_the_limit(self):
        settings.RATE_LIMIT_WRITES_PER_MINUTE = 2
        payload = {"fileName": "x.csv", "content": "a,b\n1,2\n"}
        for i in range(2):
            client.post("/api/csv/preview", json=payload,
                        headers={"X-Forwarded-For": f"10.0.0.{i}"})
        # A client-supplied header must not mint a fresh bucket on demand.
        resp = client.post("/api/csv/preview", json=payload,
                           headers={"X-Forwarded-For": "10.0.0.99"})
        self.assertEqual(resp.status_code, 429)


@pytest.mark.unit
class AuditWriterContract(unittest.TestCase):
    """O-04: the shared audit writer's guardrails, without touching a database."""

    def test_only_known_actions_are_accepted(self):
        self.assertEqual(VALID_ACTIONS, {"upload", "delete", "password_reset"})

    def test_unknown_action_raises_before_any_sql_runs(self):
        class ExplodingCursor:
            def execute(self, *a, **k):
                raise AssertionError("execute must not be reached for a bad action")

        with self.assertRaises(ValueError):
            write_audit(ExplodingCursor(), "drop_everything", 1, "f.csv", "t", "dynamic")

    def test_valid_action_reaches_the_cursor_with_bound_parameters(self):
        captured = {}

        class RecordingCursor:
            def execute(self, statement, params=None):
                captured["params"] = params

        write_audit(RecordingCursor(), "upload", 7, "f.csv", "csv_abc", "dynamic")
        self.assertEqual(captured["params"],
                         ("upload", 7, "f.csv", "csv_abc", "dynamic", None, None, None))

    def test_file_id_is_coerced_from_the_loaders_string_form(self):
        self.assertEqual(coerce_file_id("42"), 42)
        self.assertEqual(coerce_file_id(42), 42)

    def test_unparseable_file_id_degrades_to_null_rather_than_raising(self):
        # Losing the id is survivable; losing the whole audit row is not.
        self.assertIsNone(coerce_file_id("not-a-number"))
        self.assertIsNone(coerce_file_id(None))
        self.assertIsNone(coerce_file_id({"unexpected": "shape"}))
