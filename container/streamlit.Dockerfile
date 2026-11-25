# te-streamlit: the Streamlit front end (#256). Build from the repo root:
#   docker build -f container/streamlit.Dockerfile -t te-streamlit:dev .
# Deployed to Azure Container Apps beside the API (infra/terraform-prod). Only the app is copied: it talks to
# the API over HTTP (API_URL) and holds no database credentials. API_URL and MAX_UPLOAD_BYTES arrive as
# environment variables at run time; nothing is baked in.
# #327: the base image is pinned by digest (the tag alone can move under the same name); Dependabot's docker
# ecosystem proposes the new digest when the tag moves. Python 3.12: DECISIONS/2026-11-24-one-python-version.md.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Same Debian security update as the API image (#326): zlib1g and libzstd1. Does nothing once the base image carries the fix.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g libzstd1 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app
WORKDIR /app/streamlit_app

# #327: the hashed lock (scripts/lock_requirements.sh), so two builds install the same code, verified.
COPY streamlit_app/requirements.lock requirements.lock
RUN pip install --require-hashes --no-deps -r requirements.lock

# streamlit_app/ includes .streamlit/config.toml, which Streamlit reads from the folder it starts in (this
# WORKDIR): usage statistics off (browser.gatherUsageStats = false) and the upload limit (server.maxUploadSize).
COPY streamlit_app/ ./

USER app
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.address", "0.0.0.0", "--server.port", "8501"]
