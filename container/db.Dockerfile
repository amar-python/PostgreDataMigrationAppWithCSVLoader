# te-db: PostgreSQL 16 that deploys the T&E schema the first time it starts (#128, BR-38).
# Build from the repo root:  docker build -f container/db.Dockerfile -t te-db:dev .
# Only the three files the deployer needs are copied; the passwords arrive as environment
# variables on first start, so none is in the image.
#
# gosu (the helper the official entrypoint uses to drop from root to postgres) is rebuilt here.
# The official image ships a gosu built with Go 1.24.6, and the image scan (#326) reports 26 known
# vulnerabilities in the Go standard library inside it, one CRITICAL. The fixes need Go 1.26.10 or
# newer, and the upstream image has not been rebuilt with one. So gosu is built from its release
# tag with a current Go, and the build stops if the golang image is older than the minimum below.
# This image therefore carries gosu built from the upstream source tag, not upstream's signed
# release binary; Go checks the dependencies against go.sum and the checksum database. Building
# it needs to reach github.com and the Go module proxy (as the other images already need PyPI and npm).
# #327: the base image is pinned by digest (the tag alone can move under the same name); Dependabot's docker
# ecosystem proposes the new digest when the tag moves. The tag stays for people and for Dependabot.
FROM golang:1.26@sha256:4165ee6bf3b7811fd7b40373290405c83d0167dcb87ee5f29c427cdcef45ff8f AS gosu
ARG GO_MINIMUM_VERSION=1.26.10
ARG GOSU_VERSION=1.19
ENV GOTOOLCHAIN=local
RUN set -eux; \
    have="$(go env GOVERSION | sed 's/^go//')"; \
    if ! printf '%s\n%s\n' "$GO_MINIMUM_VERSION" "$have" | sort -V -C; then \
        echo "the golang image has Go $have; gosu needs $GO_MINIMUM_VERSION or newer" >&2; \
        exit 1; \
    fi; \
    git clone --quiet --depth 1 --branch "$GOSU_VERSION" https://github.com/tianon/gosu /src; \
    mkdir -p /out; \
    cd /src; \
    CGO_ENABLED=0 go build -trimpath -ldflags '-s -w' -o /out/gosu .; \
    go version -m /out/gosu | head -n 1; \
    /out/gosu --version

FROM postgres:16@sha256:3950ad7c3148ca2175ef1b6c36c9efbf78957ae8fbe8b3a5d7c35af50500382f

# Debian's security updates for the packages the image scan flagged (#326): zlib1g and the
# Kerberos libraries. The base image is rebuilt only now and then; the fixes are in Debian's
# archive sooner. Only the named packages are upgraded (a blanket upgrade could move PostgreSQL
# itself), and the line does nothing once the base image carries the fixes.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade \
      zlib1g libgssapi-krb5-2 libkrb5-3 libk5crypto3 libkrb5support0 \
 && rm -rf /var/lib/apt/lists/*

# The rebuilt gosu replaces the official one at the same path (docker-entrypoint.sh calls it
# from the PATH). Run it once, as the official image does, so a broken binary fails the build.
COPY --from=gosu /out/gosu /usr/local/bin/gosu
RUN gosu --version && gosu nobody true

COPY build/deploy_all.sh                          /opt/te/build/deploy_all.sh
COPY build/te_core_schema.sql                     /opt/te/build/te_core_schema.sql
COPY build/environments/env_prod.example.sql      /opt/te/build/environments/env_prod.example.sql
# The official image runs everything in this directory once, when the data directory is
# empty. A restart, or a new container on the same volume, does not run it again.
COPY container/db-init.sh /docker-entrypoint-initdb.d/10-te-schema.sh
