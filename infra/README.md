# infra/

Deployment artefacts for the migration runner and the Azure environment stacks.

| Path | What it is |
| --- | --- |
| `Dockerfile` | The migration runner image: deploys the schema, loads input CSVs, runs the eval suite. Not the application — see #128 for the application container bundle. |
| `entrypoint.sh` | Dispatches the container's action: `deploy` \| `load` \| `evals` \| `full` \| `shell`. |
| `terraform/` | Dev stack. |
| `terraform-prod/` | Production stack. See `docs/PROD_DEPLOY.md`. |
| `terraform-test/`, `terraform-staging/` | Test and staging stacks. Code only — the one-time Azure setup in #31 has not been done, so these cannot be applied yet. |
| `cloudshell_setup.sh` | The one-time setup for those two stacks (Terraform state storage, optional GitHub Actions identity), run in Azure Cloud Shell because `az` and `terraform` cannot run on the dev machine (#32, #34). See `docs/CLOUD_SHELL_SETUP.md`. |
| `azure-portal-walkthrough.md` | Click-through for the portal steps. |

## Never let a credential into an image layer

Image layers are immutable and cached indefinitely. Once a password reaches a
layer that has been pushed to a registry — private registries included —
rotating that password is the only remediation, and only if somebody notices.
Treat a credential in a layer as disclosed.

`.gitignore` does **not** filter the Docker build context. A file can be
correctly gitignored, absent from every commit, and still be copied into the
image, because `docker build` sends the working tree as it stands on the
machine running the build. Two files in this repository are exactly that shape:

- `build/config.local.env` — written by `build/setup.sh` and
  `scripts/provision_full_test_env.sh`, holds the developer's real dev
  credentials.
- `build/environments/env_<env>.sql` — generated from the committed
  `.example.sql` templates, holds `app_password` for that environment.

So the image keeps them out twice over (RV-S4, #174), because either layer
alone is one edit away from being wrong:

1. **`.dockerignore`** lists both, mirroring `.gitignore` lines 2–8. The
   `.example.sql` templates are re-included — the image needs those.
2. **`Dockerfile` names an explicit source list** for `build/`, rather than
   `COPY build/ ./build/`. Nothing under `build/` reaches the image unless a
   `COPY` asks for it by name.

Layer 1 stops the files we know about. Layer 2 is what still holds when someone
adds a new config file under `build/` and does not think of this page.

**Adding a file to the image means adding a `COPY` for it on purpose.** If you
add one, check it is not generated, not gitignored, and carries no secret.

`tests/test_docker_image_secrets.py` enforces both layers with no Docker daemon
required: it synthesises the credential files, expands the Dockerfile's `COPY`
sources, and asserts none of them is reachable — while asserting the templates
and `deploy_all.sh` still are.
