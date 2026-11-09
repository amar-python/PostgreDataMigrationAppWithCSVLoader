"""Tenant T&E schemas have an upgrade path (#184).

Before: api/tenancy.py cloned only the T&E tables a tenant was missing and returned. A change to
the template (#177's composite keys) never reached a tenant that already had its tables.

Now each tenant's T&E tables carry a version (alembic_te/, table alembic_version_te) and
migrate_tenant brings them to head. The property that matters is *parity*: a tenant reached by
any route (cloned, upgraded from the baseline, adopted from before versioning, cloned from an
older template) ends up structurally identical to the template.

The "old shape" fixture is the template's own tables run back to te0001 by the chain's downgrade,
and its shape is asserted below, so the test does not take the downgrade on trust.

Integration tests need a live PostgreSQL with the template (te_dev) deployed and seeded.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from psycopg2 import sql

from api.config import TE_TABLES, settings
from api.db import APPEND_ONLY, owner_connect
from api.tenancy import (TE_BASELINE, TE_VERSION_TABLE, _te_config, migrate_te_schema, migrate_tenant,
                         provision_te_tables, schema_for, te_head, template_te_version)

ROOT = Path(__file__).resolve().parent.parent
_PROGRAM_TABLES = ("test_cases", "test_events", "vcrm_entries", "test_results")


@pytest.mark.unit
class TheChain(unittest.TestCase):
    def test_it_is_linear_and_starts_at_the_baseline(self):
        script = ScriptDirectory.from_config(_te_config("unused"))
        self.assertEqual([r.revision for r in script.walk_revisions()], ["te0002", "te0001"])
        self.assertEqual(TE_BASELINE, "te0001")

    def test_both_copies_of_the_schema_file_stamp_the_head(self):
        for path in ("build/te_core_schema.sql", "build/schema/postgresql/te_core_schema.sql"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn(f"IS 'te_schema_version={te_head()}'", text,
                          f"{path} must stamp the newest migration; bump it with the migration")

    def test_the_runtime_role_cannot_rewrite_the_version_table(self):
        self.assertIn(TE_VERSION_TABLE, APPEND_ONLY)


def signature(cur, schema: str) -> dict[str, list]:
    """Everything about a schema's T&E tables that a migration could change, with its own name removed."""
    def norm(text):
        return None if text is None else re.sub(rf'(?<![\w"]){re.escape(schema)}\.', "<S>.", text)

    sig: dict[str, list] = {}
    cur.execute("SELECT table_name, column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = %s AND table_name = ANY(%s)",
                (schema, TE_TABLES))
    sig["columns"] = sorted((t, c, d, n, norm(df)) for t, c, d, n, df in cur.fetchall())
    cur.execute("SELECT r.relname, c.conname, c.contype, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class r ON r.oid = c.conrelid WHERE r.relnamespace = %s::regnamespace "
                "AND r.relname = ANY(%s)", (schema, TE_TABLES))
    sig["constraints"] = sorted((t, n, k, norm(d)) for t, n, k, d in cur.fetchall())
    cur.execute("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = %s "
                "AND tablename = ANY(%s)", (schema, TE_TABLES))
    sig["indexes"] = sorted((t, n, norm(d)) for t, n, d in cur.fetchall())
    cur.execute("SELECT r.relname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "JOIN pg_class r ON r.oid = t.tgrelid WHERE r.relnamespace = %s::regnamespace "
                "AND r.relname = ANY(%s) AND NOT t.tgisinternal", (schema, TE_TABLES))
    sig["triggers"] = sorted((t, n, norm(d)) for t, n, d in cur.fetchall())
    cur.execute("SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p WHERE "
                "p.pronamespace = %s::regnamespace AND p.proname IN ('set_updated_at', 'te_fill_program_id')",
                (schema,))
    sig["functions"] = sorted((n, norm(d)) for n, d in cur.fetchall())
    return sig


@pytest.mark.integration
class TenantTeSchemaUpgrades(unittest.TestCase):
    def setUp(self):
        self.tag = uuid.uuid4().hex[:10]
        self.slug = f"tem_{self.tag}"
        self.schema = schema_for(self.slug)
        self.scratch: list[str] = []
        self._template = settings.TE_SCHEMA
        with owner_connect() as conn, conn.cursor() as cur:
            self.template_sig = signature(cur, self._template)
        self.assertTrue(self.template_sig["columns"], f"the template schema {self._template!r} is not deployed")

    def tearDown(self):
        settings.TE_SCHEMA = self._template
        with owner_connect() as conn, conn.cursor() as cur:
            for schema in [self.schema, *self.scratch]:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            conn.commit()

    # -- helpers ---------------------------------------------------------------------------

    def _q(self, query, args=()):
        """Run one statement and commit it; the rows if it returned any."""
        with owner_connect() as conn, conn.cursor() as cur:
            cur.execute(query, args)
            rows = cur.fetchall() if cur.description else None
            conn.commit()
            return rows

    def _signature(self, schema=None):
        with owner_connect() as conn, conn.cursor() as cur:
            return signature(cur, schema or self.schema)

    def _version(self) -> str | None:
        rows = self._q(sql.SQL("SELECT version_num FROM {}.{}").format(
            sql.Identifier(self.schema), sql.Identifier(TE_VERSION_TABLE)))
        return rows[0][0] if rows else None

    def _assert_matches_template(self, schema=None):
        actual = self._signature(schema)
        for part, expected in self.template_sig.items():
            missing, extra = sorted(set(expected) - set(actual[part])), sorted(set(actual[part]) - set(expected))
            self.assertEqual((missing, extra), ([], []),
                             f"{part}: the tenant lacks the first list and has the second beyond the template")

    def _migrate(self) -> str:
        with owner_connect() as conn, conn.cursor() as cur:
            return migrate_te_schema(conn, cur, self.schema)

    def _make_old_shape_tenant(self):
        """A tenant as it was before #177, with the template's seed rows in it, and no version table."""
        migrate_tenant(self.slug)
        command.downgrade(_te_config(self.schema), TE_BASELINE)
        with owner_connect() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE {}.{}").format(sql.Identifier(self.schema),
                                                           sql.Identifier(TE_VERSION_TABLE)))
            for table in TE_TABLES:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                            "AND table_name = %s", (self.schema, table))
                mine = {r[0] for r in cur.fetchall()}
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                            "AND table_name = %s", (self._template, table))
                cols = sql.SQL(", ").join(sql.Identifier(c) for c in sorted(mine & {r[0] for r in cur.fetchall()}))
                cur.execute(sql.SQL("INSERT INTO {s}.{t} ({c}) SELECT {c} FROM {tpl}.{t}").format(
                    s=sql.Identifier(self.schema), t=sql.Identifier(table), c=cols,
                    tpl=sql.Identifier(self._template)))
            conn.commit()
        seeded = self._q(sql.SQL("SELECT (SELECT count(*) FROM {t}.test_programs), (SELECT count(*) FROM {t}.vcrm_entries)")
                         .format(t=sql.Identifier(self._template)))[0]
        self.assertTrue(seeded[0] >= 2 and seeded[1] >= 1,
                        f"the template needs seed rows for two programs and a VCRM entry (SEED_DEV=true); has {seeded}")

    # -- paths to the template's shape -----------------------------------------------------

    def test_a_new_tenant_is_cloned_stamped_at_head_and_matches_the_template(self):
        migrate_tenant(self.slug)
        self.assertEqual(self._version(), te_head())
        self._assert_matches_template()

    def test_the_template_is_stamped_with_the_head(self):
        with owner_connect() as conn, conn.cursor() as cur:
            self.assertEqual(template_te_version(cur, self._template), te_head())

    def test_running_again_changes_nothing(self):
        migrate_tenant(self.slug)
        before = self._signature()
        self.assertEqual(self._migrate(), "upgraded")
        self.assertEqual(self._signature(), before)

    def test_downgrade_restores_the_shape_from_before_177_and_upgrade_restores_the_template(self):
        migrate_tenant(self.slug)
        command.downgrade(_te_config(self.schema), TE_BASELINE)
        sig = self._signature()
        for table in _PROGRAM_TABLES:
            self.assertNotIn((table, "program_id"), [(t, c) for t, c, *_ in sig["columns"]], table)
        self.assertEqual([t for t in sig["triggers"] if t[1] == "trg_fill_program_id"], [])
        self.assertEqual(sig["functions"][0][0], "set_updated_at")
        self.assertEqual(len(sig["functions"]), 1, "te_fill_program_id must be gone")
        fks = [d for t, n, k, d in sig["constraints"] if t == "test_cases" and k == "f" and "phase_id" in d]
        self.assertEqual(fks, ["FOREIGN KEY (phase_id) REFERENCES <S>.test_phases(phase_id) ON DELETE CASCADE"])
        command.upgrade(_te_config(self.schema), "head")
        self._assert_matches_template()

    def test_a_tenant_from_before_versioning_is_adopted_and_keeps_its_data(self):
        self._make_old_shape_tenant()
        updated_before = self._q(sql.SQL("SELECT tc_id, updated_at FROM {}.test_cases ORDER BY tc_id").format(
            sql.Identifier(self.schema)))
        self.assertTrue(updated_before)
        self.assertEqual(self._migrate(), "adopted")
        self.assertEqual(self._version(), te_head())
        self._assert_matches_template()
        # program_id came from each row's parent, so it equals the template's value for the same row
        for table, key in (("test_cases", "tc_id"), ("test_events", "event_id"),
                           ("vcrm_entries", "vcrm_id"), ("test_results", "result_id")):
            mine = self._q(sql.SQL("SELECT {k}, program_id FROM {}.{} ORDER BY {k}").format(
                sql.Identifier(self.schema), sql.Identifier(table), k=sql.Identifier(key)))
            theirs = self._q(sql.SQL("SELECT {k}, program_id FROM {}.{} WHERE {k} = ANY(%s::uuid[]) ORDER BY {k}").format(
                sql.Identifier(self._template), sql.Identifier(table), k=sql.Identifier(key)),
                ([r[0] for r in mine],))
            self.assertEqual(mine, theirs, table)
        self.assertEqual(self._q(sql.SQL("SELECT tc_id, updated_at FROM {}.test_cases ORDER BY tc_id").format(
            sql.Identifier(self.schema))), updated_before, "the backfill must not look like an edit")

    def test_a_tenant_cloned_after_177_with_default_constraint_names_is_adopted_without_duplicates(self):
        migrate_tenant(self.slug)
        s = sql.Identifier(self.schema)
        self._q(sql.SQL("ALTER TABLE {}.test_phases RENAME CONSTRAINT uq_phases_id_program "
                        "TO test_phases_phase_id_program_id_key").format(s))
        self._q(sql.SQL("DROP TABLE {}.{}").format(s, sql.Identifier(TE_VERSION_TABLE)))
        self.assertEqual(self._migrate(), "adopted")
        self._assert_matches_template()
        unique_on_phases = self._q(sql.SQL(
            "SELECT count(*) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'u' "
            "AND pg_get_constraintdef(oid) = 'UNIQUE (phase_id, program_id)'"), (f'"{self.schema}".test_phases',))
        self.assertEqual(unique_on_phases[0][0], 1, "an equivalent constraint must be renamed, not duplicated")

    def test_a_clone_carries_the_templates_index_and_constraint_names(self):
        migrate_tenant(self.slug)
        names = {n for _, n, *_ in self._signature()["indexes"]}
        self.assertLessEqual({"idx_testcases_phase", "uq_phases_id_program", "idx_personnel_email_trgm"}, names)
        # what LIKE ... INCLUDING ALL would have called the same objects
        self.assertTrue(names.isdisjoint({"test_cases_phase_id_idx", "test_phases_phase_id_program_id_key",
                                          "personnel_email_idx"}))

    def test_cross_program_rows_stop_the_upgrade_name_the_rows_and_change_nothing(self):
        self._make_old_shape_tenant()
        s = sql.Identifier(self.schema)
        # old shape: a VCRM entry may name a requirement from one program and a test case from another
        (vcrm_id, other_req), = self._q(sql.SQL(
            "SELECT v.vcrm_id, r.req_id FROM {s}.vcrm_entries v "
            "JOIN {s}.test_cases c ON c.tc_id = v.tc_id JOIN {s}.test_phases ph ON ph.phase_id = c.phase_id "
            "JOIN {s}.requirements r ON r.program_id <> ph.program_id LIMIT 1").format(s=s))
        self._q(sql.SQL("UPDATE {}.vcrm_entries SET req_id = %s WHERE vcrm_id = %s").format(s), (other_req, vcrm_id))
        before = self._signature()
        with self.assertRaises(RuntimeError) as ctx:
            self._migrate()
        self.assertIn("Nothing was changed", str(ctx.exception))
        self.assertIn(str(vcrm_id), str(ctx.exception))
        self.assertIn(self.schema, str(ctx.exception))
        self.assertEqual(self._signature(), before, "the failed upgrade must roll back completely")
        self.assertEqual(self._version(), TE_BASELINE)

    def test_a_template_at_an_older_version_is_cloned_then_brought_forward(self):
        scratch = f"te_tpl_{self.tag}"
        self.scratch.append(scratch)
        with owner_connect() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(scratch)))
            provision_te_tables(cur, scratch, self._template)
            conn.commit()
        command.stamp(_te_config(scratch), te_head())
        command.downgrade(_te_config(scratch), TE_BASELINE)
        self._q(sql.SQL("COMMENT ON SCHEMA {} IS %s").format(sql.Identifier(scratch)),
                (f"te_schema_version={TE_BASELINE}",))
        settings.TE_SCHEMA = scratch
        try:
            self.assertEqual(self._migrate_new(), "provisioned")
        finally:
            settings.TE_SCHEMA = self._template
        self.assertEqual(self._version(), te_head())
        self._assert_matches_template()

    def _migrate_new(self) -> str:
        """migrate_te_schema for a tenant that has no T&E tables yet (its schema is made if need be)."""
        self._q(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
        return self._migrate()

    def test_the_next_schema_change_reaches_existing_and_new_tenants(self):
        """The reproduction in #184: change the T&E tables after a tenant exists and it must get the change.

        A throwaway migration, te9001, is added on top of the real chain (in a temporary copy of it).
        The template is still at te0002, so a new tenant is cloned from it and brought forward too.
        """
        existing = self.slug
        migrate_tenant(existing)
        chain = Path(tempfile.mkdtemp(prefix="alembic_te_next_"))
        try:
            shutil.copytree(ROOT / "alembic_te", chain, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
            (chain / "versions" / "te9001_demo.py").write_text(
                'from alembic import op\nrevision = "te9001"\ndown_revision = "te0002"\n'
                "branch_labels = None\ndepends_on = None\n\n\ndef upgrade():\n"
                '    schema = op.get_context().opts["version_table_schema"]\n'
                '    op.execute(f\'ALTER TABLE "{schema}".organisations ADD COLUMN demo_note TEXT\')\n\n\n'
                "def downgrade():\n    pass\n", encoding="utf-8")

            def config_with_next_change(schema):
                cfg = _te_config(schema)
                cfg.set_main_option("script_location", str(chain))
                return cfg

            def has_demo_note(schema):
                return bool(self._q("SELECT 1 FROM information_schema.columns WHERE table_schema = %s "
                                    "AND table_name = 'organisations' AND column_name = 'demo_note'", (schema,)))

            with mock.patch("api.tenancy._te_config", side_effect=config_with_next_change):
                self.assertFalse(has_demo_note(self.schema))
                self.assertEqual(self._migrate(), "upgraded")
                self.assertTrue(has_demo_note(self.schema), "an existing tenant did not get the change")
                self.assertEqual(self._version(), "te9001")

                newcomer = f"tenant_tem_{uuid.uuid4().hex[:10]}"
                self.scratch.append(newcomer)
                self._q(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(newcomer)))
                with owner_connect() as conn, conn.cursor() as cur:
                    self.assertEqual(migrate_te_schema(conn, cur, newcomer), "provisioned")
                self.assertTrue(has_demo_note(newcomer), "a tenant cloned from the older template did not get it")
        finally:
            shutil.rmtree(chain, ignore_errors=True)

    def test_a_template_with_no_stamp_is_refused_with_the_way_out(self):
        scratch = f"te_tpl_{self.tag}"
        self.scratch.append(scratch)
        with owner_connect() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(scratch)))
            provision_te_tables(cur, scratch, self._template)
            conn.commit()
        settings.TE_SCHEMA = scratch
        with self.assertRaisesRegex(RuntimeError, "Redeploy it with build/deploy_all.sh"):
            self._migrate_new()
        self.assertEqual(self._q("SELECT to_regclass(%s)", (f'"{self.schema}".test_cases',))[0][0], None)

    def test_a_template_stamped_with_an_unknown_version_is_refused(self):
        scratch = f"te_tpl_{self.tag}"
        self.scratch.append(scratch)
        with owner_connect() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(scratch)))
            provision_te_tables(cur, scratch, self._template)
            cur.execute(sql.SQL("COMMENT ON SCHEMA {} IS 'te_schema_version=te9999'").format(sql.Identifier(scratch)))
            conn.commit()
        settings.TE_SCHEMA = scratch
        with self.assertRaisesRegex(RuntimeError, self.schema):
            self._migrate_new()

    def test_two_workers_starting_together_leave_one_correct_tenant(self):
        self._q(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))  # the T&E tables are what both race to build
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [f.result() for f in [pool.submit(self._migrate_new) for _ in range(2)]]
        self.assertEqual(sorted(results), ["provisioned", "upgraded"])
        self.assertEqual(self._version(), te_head())
        self._assert_matches_template()
