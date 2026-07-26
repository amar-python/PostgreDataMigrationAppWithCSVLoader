# Dockerfile — migration runner image
#
# Builds a single image that can:
#   1. Deploy the schema (build/deploy_all.sh <env>)
#   2. Load input CSVs (input_data/load_input_data.sql)
#   3. Run the eval suite (evals/runner.py --tiers p,i,s)
#
# Entrypoint dispatches on the first arg: deploy | load | evals | shell.
#
# Build from the PostgreDataMigrationApp repo root:
#   docker build -f infra/Dockerfile -t te-migration:dev .
#
# Or via az acr build (no local Docker needed):
#   az acr build --registry <acr> --image te-migration:dev --file infra/Dockerfile .
#
# Run locally (against a PG container on the same network):
#   docker run --rm \
#     -e PGHOST=postgres -e PGPORT=5432 -e PGUSER=postgres \
#     -e PGPASSWORD=devpass -e PGDATABASE=te_dev \
#     -e TARGET_ENV=dev \
#     te-migration:dev deploy

FROM python:3.11-slim AS base

# psql client + bash + curl for libpq env-var support and shell scripts
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        bash \
        curl \
        ca-certificates \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*
# NOTE: postgresql-client is the meta-package — it tracks whatever Debian
# ships (Debian 12 = client 15, Debian 13 = client 17). The PG wire
# protocol is stable across these versions, so the client talks to PG 16
# server in the Container App without trouble. Pinning to a specific
# version (e.g. postgresql-client-15) breaks the build whenever the
# python:3.11-slim base image moves to a newer Debian.

# Non-root user — never run migrations as root
RUN groupadd --gid 1001 app \
    && useradd --uid 1001 --gid app --shell /bin/bash --create-home app

WORKDIR /opt/migration

# Copy only what the runner needs (NOT the .git folder, IDE configs, etc.).
# Build context is the PostgreDataMigrationApp repo root, so paths are
# relative to that — NO `PostgreDataMigrationApp/` prefix.
COPY --chown=app:app build/        ./build/
COPY --chown=app:app tests/        ./tests/
COPY --chown=app:app evals/        ./evals/
COPY --chown=app:app infra/entrypoint.sh ./entrypoint.sh
# NOTE: input_data/ is intentionally NOT copied. It's CSV fixtures used
# only during the `load` action and lives in a separate repo / Azure
# Files mount. The entrypoint's load step skips gracefully if it isn't
# present in the image.

RUN chmod +x entrypoint.sh build/deploy_all.sh build/setup.sh 2>/dev/null || true
RUN find build -name '*.sh' -exec chmod +x {} \;

USER app

# Default env values — Container Instance / GitHub Actions override these
ENV PGHOST=localhost \
    PGPORT=5432 \
    PGUSER=postgres \
    PGDATABASE=te_dev \
    TARGET_ENV=dev \
    WAIT_FOR_DB_SECONDS=60

ENTRYPOINT ["./entrypoint.sh"]
CMD ["deploy"]
