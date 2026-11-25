FROM python:3.11-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the application, by name (#348). `COPY . .` copied the whole build folder, and from a folder inside a home
# directory that is SSH keys, cloud-CLI logins and downloads, in an image layer that one `docker push` would publish.
# The CSV and schema files the jobs name (./input_data/) are data: mount them at run time, for example
# `docker run -v "$PWD/input_data:/app/input_data" ...`. tests/test_docker_build_context.py fails if this goes back.
COPY main.py config.yaml ./
COPY src/ src/

ENTRYPOINT ["python", "main.py"]
CMD ["migrate"]
