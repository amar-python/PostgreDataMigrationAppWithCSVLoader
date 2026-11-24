# te-streamlit: the Streamlit front end (#256). Build from the repo root:
#   docker build -f container/streamlit.Dockerfile -t te-streamlit:dev .
# Deployed to Azure Container Apps beside the API (infra/terraform-prod). Only the app is copied: it talks to
# the API over HTTP (API_URL) and holds no database credentials. API_URL and MAX_UPLOAD_BYTES arrive as
# environment variables at run time; nothing is baked in.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Same Debian security update as the API image (#326): zlib1g. Does nothing once the base image carries the fix.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app
WORKDIR /app/streamlit_app

COPY streamlit_app/requirements.txt requirements.txt
RUN pip install -r requirements.txt

# streamlit_app/ includes .streamlit/config.toml, which Streamlit reads from the folder it starts in (this
# WORKDIR): usage statistics off (browser.gatherUsageStats = false) and the upload limit (server.maxUploadSize).
COPY streamlit_app/ ./

USER app
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.address", "0.0.0.0", "--server.port", "8501"]
