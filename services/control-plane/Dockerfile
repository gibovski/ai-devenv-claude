FROM docker:27.3.1-cli AS dockercli
FROM docker/compose-bin:v2.30.3 AS compose

FROM hashicorp/terraform:1.9.8 AS terraform

FROM python:3.12-slim
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends curl jq ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=terraform /bin/terraform /usr/local/bin/terraform
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_SYSTEM_PYTHON=1
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=compose /docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes -o requirements.txt && uv pip install --no-cache -r requirements.txt
COPY devenv ./devenv
RUN uv pip install --no-cache --no-deps .
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "devenv"]
