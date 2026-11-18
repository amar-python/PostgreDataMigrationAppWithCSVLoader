# te-db: PostgreSQL 16 that deploys the T&E schema the first time it starts (#128, BR-38).
# Build from the repo root:  docker build -f container/db.Dockerfile -t te-db:dev .
# Only the three files the deployer needs are copied; the passwords arrive as environment
# variables on first start, so none is in the image.
FROM postgres:16

COPY build/deploy_all.sh                          /opt/te/build/deploy_all.sh
COPY build/te_core_schema.sql                     /opt/te/build/te_core_schema.sql
COPY build/environments/env_prod.example.sql      /opt/te/build/environments/env_prod.example.sql
# The official image runs everything in this directory once, when the data directory is
# empty. A restart, or a new container on the same volume, does not run it again.
COPY container/db-init.sh /docker-entrypoint-initdb.d/10-te-schema.sh
