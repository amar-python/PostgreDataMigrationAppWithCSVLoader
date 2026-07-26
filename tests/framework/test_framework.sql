-- =============================================================================
-- DEFENCE T&E — TEST FRAMEWORK  (tests/framework/test_framework.sql)
-- =============================================================================
-- Sets up the infrastructure every test file depends on:
--   • test_results table  — collects pass/fail for every assertion
--   • assert_*  functions — the assertion library
--   • report_*  functions — summary and detail reporters
--
-- Called automatically by run_all_tests.sql — do not run in isolation.
-- =============================================================================

-- ── 1. Test results store ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS test_run_results (
   result_id    BIGSERIAL    PRIMARY KEY,
   suite        VARCHAR(100) NOT NULL,      -- e.g. 'organisations', 'vcrm'
   test_name    TEXT         NOT NULL,
   status       CHAR(4)      NOT NULL CHECK (status IN ('PASS','FAIL','SKIP')),
   expected     TEXT,
   actual       TEXT,
   message      TEXT,
   executed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE test_run_results
   IS 'Collects assertion outcomes from every test suite run.';

-- Wipe results from previous run so reports are always fresh
TRUNCATE test_run_results;


-- ── 2. Internal helper: record one assertion result ──────────────────────────

CREATE OR REPLACE FUNCTION tf_record(
   p_suite    TEXT,
   p_name     TEXT,
   p_status   TEXT,
   p_expected TEXT DEFAULT NULL,
   p_actual   TEXT DEFAULT NULL,
   p_message  TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
BEGIN
   INSERT INTO test_run_results
      (suite, test_name, status, expected, actual, message)
   VALUES
      (p_suite, p_name, p_status::CHAR(4), p_expected, p_actual, p_message);
END;
$$;


-- ── 3. Assertion library ─────────────────────────────────────────────────────

-- assert_equals: pass when actual = expected (works for any TEXT-castable type)
CREATE OR REPLACE FUNCTION assert_equals(
   p_suite    TEXT,
   p_name     TEXT,
   p_expected ANYELEMENT,
   p_actual   ANYELEMENT,
   p_message  TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
BEGIN
   IF p_actual IS NOT DISTINCT FROM p_expected THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         p_expected::TEXT, p_actual::TEXT, p_message);
   ELSE
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         p_expected::TEXT, p_actual::TEXT,
         COALESCE(p_message, 'Value mismatch'));
   END IF;
END;
$$;


-- assert_not_equals: pass when actual ≠ expected
CREATE OR REPLACE FUNCTION assert_not_equals(
   p_suite    TEXT,
   p_name     TEXT,
   p_expected ANYELEMENT,
   p_actual   ANYELEMENT,
   p_message  TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
BEGIN
   IF p_actual IS DISTINCT FROM p_expected THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         '!= ' || p_expected::TEXT, p_actual::TEXT, p_message);
   ELSE
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         '!= ' || p_expected::TEXT, p_actual::TEXT,
         COALESCE(p_message, 'Values should differ but are equal'));
   END IF;
END;
$$;


-- assert_row_count: pass when COUNT(*) of a query equals expected_count
CREATE OR REPLACE FUNCTION assert_row_count(
   p_suite          TEXT,
   p_name           TEXT,
   p_query          TEXT,
   p_expected_count BIGINT,
   p_message        TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
DECLARE
   v_actual BIGINT;
BEGIN
   EXECUTE 'SELECT COUNT(*) FROM (' || p_query || ') _q' INTO v_actual;
   PERFORM assert_equals(
      p_suite, p_name,
      p_expected_count, v_actual,
      COALESCE(p_message, 'Row count check: ' || p_query)
   );
END;
$$;


-- assert_true: pass when condition evaluates to TRUE
CREATE OR REPLACE FUNCTION assert_true(
   p_suite    TEXT,
   p_name     TEXT,
   p_query    TEXT,      -- a SQL expression that returns BOOLEAN
   p_message  TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
DECLARE
   v_result BOOLEAN;
BEGIN
   EXECUTE 'SELECT (' || p_query || ')' INTO v_result;
   IF v_result IS TRUE THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         'TRUE', 'TRUE', p_message);
   ELSE
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         'TRUE', COALESCE(v_result::TEXT,'NULL'),
         COALESCE(p_message, 'Condition was false or null'));
   END IF;
END;
$$;


-- assert_false: pass when condition evaluates to FALSE
CREATE OR REPLACE FUNCTION assert_false(
   p_suite    TEXT,
   p_name     TEXT,
   p_query    TEXT,
   p_message  TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
DECLARE
   v_result BOOLEAN;
BEGIN
   EXECUTE 'SELECT (' || p_query || ')' INTO v_result;
   IF v_result IS FALSE THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         'FALSE', 'FALSE', p_message);
   ELSE
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         'FALSE', COALESCE(v_result::TEXT,'NULL'),
         COALESCE(p_message, 'Condition was true or null'));
   END IF;
END;
$$;


-- assert_not_null: pass when a single-value query returns non-null
CREATE OR REPLACE FUNCTION assert_not_null(
   p_suite   TEXT,
   p_name    TEXT,
   p_query   TEXT,
   p_message TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
DECLARE
   v_result TEXT;
BEGIN
   EXECUTE p_query INTO v_result;
   IF v_result IS NOT NULL THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         'NOT NULL', v_result, p_message);
   ELSE
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         'NOT NULL', 'NULL',
         COALESCE(p_message, 'Expected a value but got NULL'));
   END IF;
END;
$$;


-- assert_null: pass when a single-value query returns null
CREATE OR REPLACE FUNCTION assert_null(
   p_suite   TEXT,
   p_name    TEXT,
   p_query   TEXT,
   p_message TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
DECLARE
   v_result TEXT;
BEGIN
   EXECUTE p_query INTO v_result;
   IF v_result IS NULL THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         'NULL', 'NULL', p_message);
   ELSE
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         'NULL', v_result,
         COALESCE(p_message, 'Expected NULL but got a value'));
   END IF;
END;
$$;


-- assert_raises: pass when executing p_query throws ANY exception
CREATE OR REPLACE FUNCTION assert_raises(
   p_suite   TEXT,
   p_name    TEXT,
   p_query   TEXT,
   p_message TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql AS
$$
BEGIN
   BEGIN
      EXECUTE p_query;
      -- If we get here, no exception was raised → FAIL
      PERFORM tf_record(p_suite, p_name, 'FAIL',
         'exception raised', 'no exception',
         COALESCE(p_message, 'Expected an exception but query succeeded'));
   EXCEPTION WHEN OTHERS THEN
      PERFORM tf_record(p_suite, p_name, 'PASS',
         'exception raised', SQLERRM, p_message);
   END;
END;
$$;


-- ── 4. Reporting functions ───────────────────────────────────────────────────

-- Full detail: every test result
CREATE OR REPLACE FUNCTION report_detail()
RETURNS TABLE (
   suite      VARCHAR(100),
   test_name  TEXT,
   status     CHAR(4),
   expected   TEXT,
   actual     TEXT,
   message    TEXT
)
LANGUAGE sql AS
$$
   SELECT suite, test_name, status, expected, actual, message
   FROM test_run_results
   ORDER BY suite, result_id;
$$;


-- Suite summary: pass/fail/skip counts per suite
CREATE OR REPLACE FUNCTION report_suite_summary()
RETURNS TABLE (
   suite        VARCHAR(100),
   total        BIGINT,
   passed       BIGINT,
   failed       BIGINT,
   skipped      BIGINT,
   pass_rate    TEXT,
   suite_status TEXT
)
LANGUAGE sql AS
$$
   SELECT
      suite,
      COUNT(*)                                                          AS total,
      COUNT(*) FILTER (WHERE status = 'PASS')                          AS passed,
      COUNT(*) FILTER (WHERE status = 'FAIL')                          AS failed,
      COUNT(*) FILTER (WHERE status = 'SKIP')                          AS skipped,
      ROUND(
         100.0 * COUNT(*) FILTER (WHERE status = 'PASS') / COUNT(*), 1
      )::TEXT || '%'                                                    AS pass_rate,
      CASE WHEN COUNT(*) FILTER (WHERE status = 'FAIL') = 0
           THEN '✓ ALL PASS'
           ELSE '✗ FAILURES: ' ||
                COUNT(*) FILTER (WHERE status = 'FAIL')::TEXT
      END                                                               AS suite_status
   FROM test_run_results
   GROUP BY suite
   ORDER BY suite;
$$;


-- Overall totals across all suites
CREATE OR REPLACE FUNCTION report_totals()
RETURNS TABLE (
   total_tests  BIGINT,
   passed       BIGINT,
   failed       BIGINT,
   skipped      BIGINT,
   pass_rate    TEXT,
   overall      TEXT
)
LANGUAGE sql AS
$$
   SELECT
      COUNT(*)                                          AS total_tests,
      COUNT(*) FILTER (WHERE status = 'PASS')          AS passed,
      COUNT(*) FILTER (WHERE status = 'FAIL')          AS failed,
      COUNT(*) FILTER (WHERE status = 'SKIP')          AS skipped,
      ROUND(
         100.0 * COUNT(*) FILTER (WHERE status = 'PASS') / COUNT(*), 1
      )::TEXT || '%'                                    AS pass_rate,
      CASE WHEN COUNT(*) FILTER (WHERE status = 'FAIL') = 0
           THEN '✓ ALL TESTS PASSED'
           ELSE '✗ ' || COUNT(*) FILTER (WHERE status = 'FAIL')::TEXT
                || ' TEST(S) FAILED'
      END                                               AS overall
   FROM test_run_results;
$$;


-- Failures only — for quick triage
CREATE OR REPLACE FUNCTION report_failures()
RETURNS TABLE (
   suite     VARCHAR(100),
   test_name TEXT,
   expected  TEXT,
   actual    TEXT,
   message   TEXT
)
LANGUAGE sql AS
$$
   SELECT suite, test_name, expected, actual, message
   FROM test_run_results
   WHERE status = 'FAIL'
   ORDER BY suite, result_id;
$$;

\echo '   [framework] Test framework loaded.'
