"""#256: the API and the Streamlit app on Azure Container Apps, as the owner decided on 24 Nov.

DECISIONS/2026-11-16-streamlit-migration-plan.md, "Azure host": two always-on apps in the existing internal-only
environment, private network only; Streamlit has one replica minimum and sticky sessions; API_URL is the API's
internal address and MAX_UPLOAD_BYTES matches the API's; the registry, Key Vault, managed identity and logs are
the existing ones. These read the Terraform and the Dockerfile as text. `terraform validate` was run by hand
(it needs the providers, which CI does not download); nothing here is applied to Azure.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra/terraform-prod"
MAIN = (TF / "main.tf").read_text(encoding="utf-8")
VARIABLES = (TF / "variables.tf").read_text(encoding="utf-8")
OUTPUTS = (TF / "outputs.tf").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "container/streamlit.Dockerfile").read_text(encoding="utf-8")


def resource(kind: str, name: str) -> str:
    m = re.search(rf'(?m)^resource\s+"{kind}"\s+"{name}"\s*\{{\n(.*?)\n\}}', MAIN, re.S)
    assert m, f"no {kind}.{name}"
    return m.group(1)


def variable(name: str) -> str:
    m = re.search(rf'(?m)^variable\s+"{name}"\s*\{{\n(.*?)\n\}}', VARIABLES, re.S)
    assert m, f"no variable {name}"
    return m.group(1)


def env_value(block: str, name: str) -> str:
    m = re.search(rf'env \{{\s*name\s*=\s*"{name}"\s*\n\s*(value|secret_name)\s*=\s*(.+)', block)
    assert m, f"no env {name}"
    return f"{m.group(1)}={m.group(2).strip()}"


API = resource("azurerm_container_app", "api")
ST = resource("azurerm_container_app", "streamlit")


def test_the_environment_stays_internal_only():
    assert "internal_load_balancer_enabled = true" in resource("azurerm_container_app_environment", "env")


@pytest.mark.parametrize("block", [API, ST], ids=["api", "streamlit"])
def test_both_apps_run_in_the_existing_environment_with_the_existing_identity_and_registry(block):
    assert "container_app_environment_id = azurerm_container_app_environment.env.id" in block
    assert "identity_ids = [azurerm_user_assigned_identity.runner.id]" in block
    assert "server   = azurerm_container_registry.acr.login_server" in block
    assert "identity = azurerm_user_assigned_identity.runner.id" in block


def test_the_images_come_from_the_prod_registry():
    assert 'image  = "${azurerm_container_registry.acr.login_server}/te-api:${var.api_image_tag}"' in API
    assert 'image  = "${azurerm_container_registry.acr.login_server}/te-streamlit:${var.streamlit_image_tag}"' in ST


def test_the_api_is_reachable_only_inside_the_environment():
    assert re.search(r"external_enabled\s*=\s*false", API)
    assert re.search(r"target_port\s*=\s*8000", API)


def test_streamlit_is_reachable_from_the_vnet_and_never_over_plain_http():
    # "External" in an internal environment is the VNet: the environment has no public address.
    assert re.search(r"external_enabled\s*=\s*true", ST)
    assert re.search(r"target_port\s*=\s*8501", ST)
    for block in (API, ST):
        assert re.search(r"allow_insecure_connections\s*=\s*false", block)


@pytest.mark.parametrize("block", [API, ST], ids=["api", "streamlit"])
def test_both_apps_are_always_on(block):
    assert re.search(r"min_replicas\s*=\s*1\b", block)


def test_streamlit_scales_by_the_variable_and_has_sticky_sessions():
    assert "max_replicas = var.streamlit_max_replicas" in ST
    assert 'revision_mode                = "Single"' in ST  # sticky sessions need single-revision mode
    sticky = resource("azapi_update_resource", "streamlit_sticky_sessions")
    assert "resource_id = azurerm_container_app.streamlit[0].id" in sticky
    assert re.search(r'stickySessions\s*=\s*\{\s*affinity\s*=\s*"sticky"', sticky)
    assert re.search(r"validation \{.*var\.streamlit_max_replicas >= 1", variable("streamlit_max_replicas"), re.S)


def test_streamlit_calls_the_api_at_its_internal_address():
    assert env_value(ST, "API_URL") == "value=local.api_internal_url"
    assert re.search(r'api_internal_url\s*=\s*.*"https://\$\{azurerm_container_app\.api\[0\]\.ingress\[0\]\.fqdn\}"', MAIN)


def test_both_apps_get_one_upload_limit():
    for block in (API, ST):
        assert env_value(block, "MAX_UPLOAD_BYTES") == "value=tostring(var.max_upload_bytes)"
    assert re.search(r"default\s*=\s*52428800\b", variable("max_upload_bytes"))


def test_the_upload_limit_cannot_pass_streamlits_own():
    assert "var.max_upload_bytes < 53 * 1000 * 1000" in variable("max_upload_bytes")
    config = (ROOT / "streamlit_app/.streamlit/config.toml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^maxUploadSize = 53$", config)


def test_the_api_database_passwords_come_from_key_vault():
    assert env_value(API, "PGPASSWORD") == 'secret_name="app-password"'
    assert env_value(API, "APP_DB_PASSWORD") == 'secret_name="runtime-password"'
    assert env_value(API, "APP_DB_USER") == 'value="te_prod_runtime"'
    assert "key_vault_secret_id = azurerm_key_vault_secret.app_password.id" in API
    assert "key_vault_secret_id = azurerm_key_vault_secret.runtime_password.id" in API
    assert "key_vault_id = azurerm_key_vault.kv.id" in resource("azurerm_key_vault_secret", "runtime_password")


def test_the_api_runs_as_prod_against_the_private_server():
    assert env_value(API, "API_ENV") == 'value="prod"'
    assert env_value(API, "PGHOST") == "value=azurerm_postgresql_flexible_server.pg.fqdn"
    assert env_value(API, "PGSSLMODE") == 'value="require"'


def test_streamlit_holds_no_database_secret():
    assert "secret {" not in ST
    assert "PGPASSWORD" not in ST and "APP_DB_PASSWORD" not in ST


def test_health_probes_use_each_apps_own_endpoint():
    assert API.count('path      = "/api/health"') + API.count('path          = "/api/health"') == 2
    assert ST.count('"/_stcore/health"') == 2


def test_the_vnet_can_resolve_the_apps():
    zone = resource("azurerm_private_dns_zone", "cae")
    assert "name                = azurerm_container_app_environment.env.default_domain" in zone
    record = resource("azurerm_private_dns_a_record", "cae_wildcard")
    assert 'name                = "*"' in record
    assert "records             = [azurerm_container_app_environment.env.static_ip_address]" in record
    assert "virtual_network_id    = azurerm_virtual_network.vnet.id" in resource(
        "azurerm_private_dns_zone_virtual_network_link", "cae")


def test_the_outputs_name_the_streamlit_address():
    assert 'output "streamlit_url"' in OUTPUTS
    assert 'output "api_internal_url"' in OUTPUTS


def test_the_apps_can_be_left_out_of_the_bootstrap_apply():
    assert re.search(r"default\s*=\s*true\b", variable("web_apps_enabled"))
    for block in (API, ST, resource("azapi_update_resource", "streamlit_sticky_sessions")):
        assert "count" in block and "var.web_apps_enabled ? 1 : 0" in block


# --- container/streamlit.Dockerfile -------------------------------------

def test_the_image_runs_streamlit_from_streamlit_app_as_a_non_root_user():
    assert re.search(r"(?m)^FROM python:3\.12-slim$", DOCKERFILE)
    assert re.search(r"(?m)^WORKDIR /app/streamlit_app$", DOCKERFILE)
    assert re.search(r"(?m)^COPY streamlit_app/ \./$", DOCKERFILE)  # includes .streamlit/config.toml
    assert re.search(r"(?m)^USER app$", DOCKERFILE)
    cmd = re.search(r"(?m)^CMD (.*)$", DOCKERFILE).group(1)
    for part in ('"-m", "streamlit", "run", "app.py"', '"--server.headless", "true"', '"--server.port", "8501"'):
        assert part in cmd


def test_the_image_copies_nothing_but_the_streamlit_app():
    sources = re.findall(r"(?m)^COPY\s+(\S+)", DOCKERFILE)
    assert sources and all(s.startswith("streamlit_app/") for s in sources), sources
    assert not re.search(r"(?m)^(ENV|ARG)\s+.*(PASSWORD|SECRET|TOKEN)", DOCKERFILE)


def test_the_image_takes_the_same_debian_fix_as_the_api_image():
    assert "--only-upgrade zlib1g" in DOCKERFILE
