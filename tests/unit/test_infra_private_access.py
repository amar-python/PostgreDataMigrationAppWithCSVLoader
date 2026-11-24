"""Key Vault and the container registry stay off the public network by default (#299, OIT-014).

Public access is opened only for the bootstrap apply, through `bootstrap_public_access`, which
defaults to false in every environment. A literal `public_network_access_enabled = true` would
leave the secrets store or registry internet-reachable if the manual flip were forgotten.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENVS = ["terraform-prod", "terraform-staging", "terraform-test"]

pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_no_terraform_file_hardcodes_public_network_access():
    offenders = [f"{p.relative_to(ROOT)}:{n}"
                 for p in (ROOT / "infra").rglob("*.tf")
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if re.search(r"public_network_access_enabled\s*=\s*true\b", line)]
    assert offenders == []


@pytest.mark.parametrize("env", ENVS)
def test_bootstrap_public_access_defaults_to_false(env):
    text = (ROOT / "infra" / env / "variables.tf").read_text(encoding="utf-8")
    block = re.search(r'variable\s+"bootstrap_public_access"\s*\{(.*?)\n\}', text, re.S)
    assert block, f"{env}: bootstrap_public_access is not declared"
    assert re.search(r"default\s*=\s*false\b", block.group(1)), f"{env}: must default to false"


@pytest.mark.parametrize("env", ENVS)
def test_key_vault_and_registry_use_the_bootstrap_variable(env):
    text = (ROOT / "infra" / env / "main.tf").read_text(encoding="utf-8")
    for resource in ("azurerm_key_vault", "azurerm_container_registry"):
        block = re.search(rf'resource\s+"{resource}"\s+"\w+"\s*\{{(.*?)\n\}}', text, re.S)
        if block:
            assert "public_network_access_enabled = var.bootstrap_public_access" in block.group(1), (env, resource)
