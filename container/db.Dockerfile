# te-db: PostgreSQL 16 that deploys the T&E schema the first time it starts (#128, BR-38).
# Build from the repo root:  docker build -f container/db.Dockerfile -t te-db:dev .
# Only the three files the deployer needs are copied; the passwords arrive as environment
# variables on first start, so none is in the image.
FROM postgres:16

# Debian's security updates for the packages the image scan flagged (#326): zlib1g and the
# Kerberos libraries. The base image is rebuilt only now and then; the fixes are in Debian's
# archive sooner. Only the named packages are upgraded (a blanket upgrade could move PostgreSQL
# itself), and the line does nothing once the base image carries the fixes.
# Not fixed here: /usr/local/bin/gosu is built with an older Go release, so the scan reports the Go
# standard library inside it. That needs a newer gosu build upstream; see the PR for #326.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade \
      zlib1g libgssapi-krb5-2 libkrb5-3 libk5crypto3 libkrb5support0 \
 && rm -rf /var/lib/apt/lists/*

COPY build/deploy_all.sh                         /opt/te/build/deploy_all.sh
COPY build/te_core_schema.sql                     /opt/te/build/te_core_schema.sql
COPY build/environments/env_prod.example.sql      /opt/te/build/environments/env_prod.example.sql
# The official image runs everything in this directory once, when the data directory is
# empty. A restart, or a new container on the same volume, does not run it again.
COPY container/db-init.sh /docker-entrypoint-initdb.d/10-te-schema.sh
