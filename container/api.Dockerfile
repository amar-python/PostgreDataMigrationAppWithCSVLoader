# te-api: the FastAPI backend (#128, BR-38). Build from the repo root:
#   docker build -f container/api.Dockerfile -t te-api:dev .
# Only what the API runs is copied (explicit list, as in infra/Dockerfile, #174): the
# application, both Alembic chains, and the two scripts the installer runs inside it.
# No credentials are baked in; everything arrives as environment variables at run time.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Debian's security update for the package the image scan flagged (#326): zlib1g. The base image
# is rebuilt only now and then; the fix is in Debian's archive sooner. Only the named package is
# upgraded, and the line does nothing once the base image carries the fix.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app
WORKDIR /app

COPY api/requirements.txt api/requirements.txt
RUN pip install -r api/requirements.txt

COPY api/            api/
COPY alembic/        alembic/
COPY alembic_te/     alembic_te/
COPY alembic.ini     alembic.ini
COPY scripts/create_tenant_admin.py scripts/create_tenant_admin.py
COPY container/smoke_test.py        smoke_test.py

USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
