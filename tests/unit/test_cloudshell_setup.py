"""infra/cloudshell_setup.sh: the one-time Azure setup for the Test and Staging stacks (#31).

The script runs in Azure Cloud Shell because `az` and `terraform` cannot run on the dev
machine (#32, #34). It cannot be run against Azure from here, so these tests put a stub
`az` first on PATH that logs every call and answers from canned state. What they pin is
the script's own logic: what it changes, what it leaves alone on a re-run, that --dry-run
changes nothing, and that it never calls terraform.

Needs bash, so it is marked `tooling` (the Windows job leaves it out).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "cloudshell_setup.sh"

# A stand-in for `az`: appends its arguments to $STUB_LOG and answers from environment
# knobs. Only the calls the script makes are modelled; anything else just succeeds.
AZ_STUB = r"""#!/usr/bin/env bash
echo "az $*" >> "$STUB_LOG"
case "$1 $2" in
  "account show")
    [ "${STUB_LOGGED_IN:-1}" = 1 ] || { echo "Please run 'az login' to setup account." >&2; exit 1; }
    case "$*" in
      *tenantId*) echo "${STUB_TENANT_ID:-22222222-2222-2222-2222-222222222222}" ;;
      *) echo "${STUB_SUB_ID:-11111111-1111-1111-1111-111111111111}" ;;
    esac ;;
  "account set") ;;
  "group show") [ "${STUB_GROUP_EXISTS:-0}" = 1 ] || exit 3 ;;
  "storage account")
    if [ "$3" = show ]; then [ "${STUB_ACCOUNT_EXISTS:-0}" = 1 ] || exit 3; fi ;;
  "ad app")
    case "$3" in
      list) [ "${STUB_APP_EXISTS:-0}" = 1 ] && echo "aaaaaaaa-0000-0000-0000-000000000001" ;;
      create) echo "bbbbbbbb-0000-0000-0000-000000000002" ;;
      federated-credential)
        if [ "$4" = list ] && [ "${STUB_CRED_EXISTS:-0}" = 1 ]; then echo "github-${STUB_ENV:-test}"; fi ;;
    esac ;;
  "ad sp") [ "$3" != show ] || [ "${STUB_SP_EXISTS:-0}" = 1 ] || exit 1 ;;
  "role assignment")
    if [ "$3" = list ] && [ "${STUB_ROLE_EXISTS:-0}" = 1 ]; then echo "/subscriptions/x/roleAssignments/y"; fi ;;
esac
exit 0
"""

TERRAFORM_STUB = """#!/usr/bin/env bash
echo "TERRAFORM CALLED: $*" >> "$STUB_LOG"
exit 1
"""

# Calls that change something in Azure. A dry run must make none of them.
MUTATING = (
    "group create", "storage account create", "storage container create", "ad app create",
    "ad sp create", "role assignment create", "federated-credential create",
)


class CloudShellSetup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bin = Path(self._tmp.name) / "bin"
        self.bin.mkdir()
        self.log = Path(self._tmp.name) / "calls.log"
        self.log.write_text("")
        for name, body in (("az", AZ_STUB), ("terraform", TERRAFORM_STUB)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)

    def run_script(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        full = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(self.log), **env}
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                              env=full, timeout=60)

    @property
    def calls(self) -> list[str]:
        return [line for line in self.log.read_text(encoding="utf-8").splitlines() if line]

    def mutating(self) -> list[str]:
        return [c for c in self.calls if any(m in c for m in MUTATING)]

    def account_name(self, res: subprocess.CompletedProcess) -> str:
        found = re.search(r"State account:\s+(\S+)", res.stdout)
        self.assertIsNotNone(found, res.stdout)
        return found.group(1)

    # -- arguments ---------------------------------------------------------------

    def test_the_script_parses(self):
        res = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_an_environment_is_required(self):
        res = self.run_script()
        self.assertEqual(res.returncode, 2)
        self.assertIn("must be 'test' or 'staging'", res.stderr)
        self.assertEqual(self.calls, [], "nothing is called before the arguments are valid")

    def test_prod_is_refused_and_pointed_at_the_manual_procedure(self):
        res = self.run_script("prod")
        self.assertEqual(res.returncode, 2)
        self.assertIn("docs/PROD_DEPLOY.md", res.stderr)
        self.assertEqual(self.calls, [])

    def test_an_unknown_option_is_refused(self):
        res = self.run_script("test", "--nope")
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown option", res.stderr)

    def test_two_environments_are_refused(self):
        self.assertEqual(self.run_script("test", "staging").returncode, 2)

    def test_not_being_signed_in_is_a_clear_error_that_changes_nothing(self):
        res = self.run_script("test", STUB_LOGGED_IN="0")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not signed in", res.stderr)
        self.assertEqual(self.mutating(), [])

    # -- the state storage -------------------------------------------------------

    def test_creates_the_state_group_account_and_container(self):
        res = self.run_script("test")
        self.assertEqual(res.returncode, 0, res.stderr)
        account = self.account_name(res)
        made = self.mutating()
        self.assertEqual(len(made), 3, made)
        self.assertIn("az group create --name rg-tfstate --location australiaeast", made[0])
        self.assertIn(f"az storage account create --name {account} --resource-group rg-tfstate", made[1])
        for flag in ("--sku Standard_LRS", "--min-tls-version TLS1_2", "--allow-blob-public-access false"):
            self.assertIn(flag, made[1])
        self.assertIn(f"az storage container create --account-name {account} --name tfstate", made[2])

    def test_the_region_is_used(self):
        self.run_script("staging", "--region", "australiasoutheast")
        self.assertTrue(any("--location australiasoutheast" in c for c in self.mutating()), self.mutating())

    def test_the_account_name_is_valid_stable_and_per_environment_and_subscription(self):
        names = {key: self.account_name(self.run_script(*args, **env))
                 for key, args, env in (
                     ("test", ("test",), {}),
                     ("test again", ("test",), {}),
                     ("staging", ("staging",), {}),
                     ("other sub", ("test",), {"STUB_SUB_ID": "99999999-9999-9999-9999-999999999999"}),
                 )}
        self.assertEqual(names["test"], names["test again"], "a re-run must find the same account")
        self.assertEqual(len({names["test"], names["staging"], names["other sub"]}), 3)
        for name in names.values():
            self.assertRegex(name, r"^sttfstate(test|staging)[0-9a-f]{6}$")
            self.assertLessEqual(len(name), 24)

    def test_existing_resources_are_reused_not_recreated(self):
        res = self.run_script("test", STUB_GROUP_EXISTS="1", STUB_ACCOUNT_EXISTS="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("reusing it", res.stdout)
        made = self.mutating()
        self.assertFalse(any("group create" in c for c in made), made)
        self.assertFalse(any("storage account create" in c for c in made), made)
        self.assertTrue(any("storage container create" in c for c in made), "idempotent, so always run")

    def test_the_subscription_option_selects_it(self):
        self.run_script("test", "--subscription", "my-sub")
        self.assertIn("az account set --subscription my-sub", self.calls)

    # -- dry run -----------------------------------------------------------------

    def test_dry_run_prints_the_changes_and_makes_none(self):
        res = self.run_script("test", "--dry-run", "--with-oidc", "octo/app")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.mutating(), [], "a dry run must not change anything")
        self.assertIn("DRY RUN", res.stdout)
        for expected in ("+ az group create", "+ az storage account create", "+ az storage container create",
                         "+ az ad app create", "+ az ad sp create", "+ az role assignment create",
                         "+ az ad app federated-credential create"):
            self.assertIn(expected, res.stdout + res.stderr)

    # -- the backend hand-off ----------------------------------------------------

    def test_prints_the_backend_block_to_paste(self):
        res = self.run_script("staging")
        account = self.account_name(res)
        self.assertIn(f'storage_account_name = "{account}"', res.stdout)
        self.assertIn('key                  = "te-staging.tfstate"', res.stdout)
        self.assertIn("infra/terraform-staging/main.tf", res.stdout)

    def test_never_runs_terraform(self):
        self.run_script("test", "--with-oidc", "octo/app")
        self.run_script("staging", "--dry-run")
        self.assertFalse(any("TERRAFORM" in c for c in self.calls), self.calls)

    # -- optional OIDC -----------------------------------------------------------

    def test_without_with_oidc_no_identity_is_touched(self):
        self.run_script("test")
        self.assertFalse(any(c.startswith(("az ad ", "az role ")) for c in self.calls), self.calls)

    def test_oidc_creates_app_principal_roles_and_a_credential_bound_to_the_environment(self):
        res = self.run_script("test", "--with-oidc", "octo/app")
        self.assertEqual(res.returncode, 0, res.stderr)
        calls = "\n".join(self.mutating())
        self.assertIn("az ad app create --display-name sp-te-github-actions-test", calls)
        self.assertIn("az ad sp create --id bbbbbbbb-0000-0000-0000-000000000002", calls)
        self.assertIn("--role Contributor", calls)
        self.assertIn("--role User Access Administrator", calls)
        self.assertIn('"subject": "repo:octo/app:environment:test"', calls)
        self.assertRegex(res.stdout, r"AZURE_TEST_CLIENT_ID\s+= bbbbbbbb-0000-0000-0000-000000000002")
        self.assertRegex(res.stdout, r"AZURE_TEST_SUBSCRIPTION_ID\s+= 11111111-1111-1111-1111-111111111111")
        self.assertRegex(res.stdout, r"AZURE_TENANT_ID\s+= 22222222-2222-2222-2222-222222222222")

    def test_oidc_reuses_what_exists(self):
        res = self.run_script("test", "--with-oidc", "octo/app", STUB_APP_EXISTS="1", STUB_SP_EXISTS="1",
                              STUB_ROLE_EXISTS="1", STUB_CRED_EXISTS="1", STUB_ENV="test")
        self.assertEqual(res.returncode, 0, res.stderr)
        made = self.mutating()
        for call in ("ad app create", "ad sp create", "role assignment create", "federated-credential create"):
            self.assertFalse(any(call in c for c in made), (call, made))
        self.assertIn("aaaaaaaa-0000-0000-0000-000000000001", res.stdout, "uses the existing app's id")

    def test_oidc_repo_must_be_owner_slash_repo(self):
        for bad in ("justone", "a/b/c", "/lead", "trail/", "has space/x"):
            with self.subTest(repo=bad):
                res = self.run_script("test", "--with-oidc", bad)
                self.assertEqual(res.returncode, 2, bad)
                self.assertIn("OWNER/REPO", res.stderr)
                self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
