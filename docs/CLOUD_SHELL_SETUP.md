# Setting up Azure from Cloud Shell (#31)

How to do the one-time Azure setup for the **Test** and **Staging** stacks without `az` or
`terraform` on the dev machine. It is the route chosen for #32 and #34.

## Why Cloud Shell

On the dev machine, Norton 360 intercepts HTTPS and re-signs it with its own root CA. That
breaks two tools in two different ways:

- **`az` (#32):** Norton's CA is trusted by Windows, but `az` ships its own Python and
  certificate bundle, and OpenSSL rejects Norton's CA because it does not mark its Basic
  Constraints extension critical. Trusting it more does not help.
- **`terraform` (#34):** Terraform's own local connection to its provider plugin fails a TLS
  check, so no command that loads a provider (`init`, `validate`, `plan`, `apply`) works, for
  any stack. The Norton attribution here is circumstantial: the clock, the Terraform version
  and the provider cache were each ruled out, and Norton's kernel-level drivers are present,
  but the mechanism was not proven.

Both were investigated in August (see the two issues), and the decision on 14 Aug was to leave
Norton and TLS verification untouched. Cloud Shell runs `az` and `terraform` on Azure's side,
outside the machine, so neither problem applies. **This does not fix the dev machine**: `az`
and `terraform` still fail there. Nothing in the application needs them. Running and testing
the app locally is unaffected.

## What you need

- An Azure subscription where your sign-in can create resource groups, storage accounts and
  role assignments (Owner is enough).
- A browser. Cloud Shell is at <https://portal.azure.com> (the `>_` button; choose **Bash**).
- Permission to read this repository from Cloud Shell. If the repository is private, use a
  fine-grained token with read access to it, or upload the `infra/` folder with Cloud Shell's
  upload button instead of cloning.

## 1. Get the repository into Cloud Shell

```bash
git clone https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader.git
cd PostgreDataMigrationAppWithCSVLoader
```

Cloud Shell is already signed in to Azure. If you have more than one subscription, pick the
right one now (`az account list -o table`, then `az account set --subscription <id>`), or pass
`--subscription` to the script.

## 2. Dry run, then run

Always read the dry run first. It prints every change the script would make and makes none.

```bash
bash infra/cloudshell_setup.sh test --dry-run
bash infra/cloudshell_setup.sh test

bash infra/cloudshell_setup.sh staging --dry-run
bash infra/cloudshell_setup.sh staging
```

For each environment it creates, in the same way as "One-time setup" in
[`PROD_DEPLOY.md`](PROD_DEPLOY.md):

- the resource group `rg-tfstate` (shared by all environments' state), if it is not there;
- a storage account for that environment's state, named `sttfstate<env><6 hex>`, with TLS 1.2
  as the minimum and public blob access off;
- the `tfstate` container in it.

It is safe to run again: the account name is derived from the subscription id and the
environment, so a second run finds and reuses the same account.

It does **not** run Terraform, edit the repository or touch GitHub. At the end it prints the
exact `backend` block to use.

## 3. Point the stack at that state

In `infra/terraform-test/main.tf` (or `terraform-staging`), uncomment the `backend "azurerm"`
block and set `storage_account_name` to the name the script printed. Make this edit in two
places: in the Cloud Shell clone, so the next step uses it, and on a branch through a pull
request, so the repository has it too. The GitHub web editor is the easiest way to do the
second.

## 4. Plan, and only then apply

```bash
cd infra/terraform-test            # or terraform-staging
cp terraform.tfvars.example terraform.tfvars   # adjust sizes if you want them smaller
terraform init
terraform plan -out tfplan
```

Terraform in Cloud Shell uses your Cloud Shell sign-in. Read the plan, and the cost note at the
top of `main.tf`: each stack costs roughly **AUD 285 to 385 a month** at the default sizes
(a managed PostgreSQL Flexible Server, ACR Premium, private endpoints, a Container Apps Job).
Apply only when you mean to:

```bash
terraform apply tfplan
```

State is in Azure storage, so it survives Cloud Shell's idle timeout. Your Cloud Shell home
directory keeps the clone between sessions.

## Optional: an identity for GitHub Actions

Only needed if you later add a pipeline that deploys to these environments. **No Azure workflow
has ever been committed to this repository**, even though `PROD_DEPLOY.md` describes some, so
today nothing would use it. If you want it anyway:

```bash
bash infra/cloudshell_setup.sh test --with-oidc amar-python/PostgreDataMigrationAppWithCSVLoader
```

This also creates an app registration `sp-te-github-actions-<env>`, its service principal, and a
federated credential bound to the GitHub Environment named `<env>`. It prints the secret
values to put in that GitHub Environment. The principal gets Contributor and User Access
Administrator on the whole subscription, exactly as in `PROD_DEPLOY.md`: narrow that once the
resource group exists.

## If something fails

- **"not signed in to Azure"**: in Cloud Shell, close and reopen it; elsewhere run `az login`.
- **The storage account name is taken**: the name is derived from your subscription id, so
  another subscription owns it. That should not happen; if it does, report it rather than
  editing the name by hand.
- **Authorization errors creating the app registration or role assignments** (only with
  `--with-oidc`): your account lacks rights in the tenant. Leave `--with-oidc` out; state
  storage does not need it.

## Status of this procedure

The script is tested against a stub `az` (`tests/unit/test_cloudshell_setup.py`): the order of
changes, that a re-run reuses what exists, that `--dry-run` changes nothing, and that Terraform
is never called. It has **not** been run against a real subscription, because that needs Azure
access the developers of this change did not have. Its first real run is its first real test,
which is why the dry run comes first. If a command fails in Cloud Shell, copy the exact error
into #31.

## How this maps to #31's checklist

| #31 item | Where it is done |
| --- | --- |
| Create Terraform state storage (storage account and `tfstate` container) | step 2 |
| Uncomment the `backend "azurerm"` block and set the account name | step 3 |
| Service principal with OIDC | optional, `--with-oidc` |
| GitHub Environment and secrets | by hand, in GitHub, only if a pipeline is added |
| `terraform init` / `plan`, reviewed before `apply` | step 4 |
