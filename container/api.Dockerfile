# te-api: the FastAPI backend (#128, BR-38). Build from the repo root:
#   docker build -f container/api.Dockerfile -t te-api:dev .
# Only what the API runs is copied (explicit list, as in infra/Dockerfile, #174): the
# application, both Alembic chains, and the two scripts the installer runs inside it.
# No credentials are baked in; everything arrives as environment variables at run time.
# #327: the base image is pinned by digest (the tag alone can move under the same name); Dependabot's docker
# ecosystem proposes the new digest when the tag moves. The tag stays for people and for Dependabot.
# Python 3.12: the one supported version (DECISIONS/2026-11-24-one-python-version.md).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Debian's security update for the packages the image scan flagged (#326): zlib1g and libzstd1. The base image
# is rebuilt only now and then; the fix is in Debian's archive sooner. Only the named packages are
# upgraded, and the line does nothing once the base image carries the fix.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g libzstd1 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app
WORKDIR /app

# #327: the hashed lock (scripts/lock_requirements.sh), so two builds install the same code, verified.
COPY api/requirements.lock api/requirements.lock
RUN pip install --require-hashes --no-deps -r api/requirements.lock

COPY api/            api/
COPY alembic/        alembic/
COPY alembic_te/     alembic_te/
COPY alembic.ini     alembic.ini
COPY scripts/create_tenant_admin.py scripts/create_tenant_admin.py
COPY container/smoke_test.py        smoke_test.py

USER app
EXPOSE 8000
# #327: the same check as the api service in docker-compose.yml, so an image run on its own (Azure, docker run) has one.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health', timeout=3)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
