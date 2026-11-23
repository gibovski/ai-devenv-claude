# Agent worker images. Targets: base, claude, codex.
#   docker build --target claude -t worker-claude workers/
FROM ubuntu:24.04 AS base
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git git-lfs gnupg jq less openssh-client python3 python3-venv python3-pip \
      build-essential ripgrep unzip zip xz-utils \
 && install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends gh nodejs \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /usr/local/bin/
# Non-root agent user (ubuntu:24.04 ships uid 1000 as "ubuntu"; rename it).
RUN usermod -l agent -d /home/agent -m ubuntu && groupmod -n agent ubuntu \
 && install -d -o agent -g agent /workspace /home/agent/.npm-global
ENV NPM_CONFIG_PREFIX=/home/agent/.npm-global PATH=/home/agent/.npm-global/bin:$PATH \
    WORKSPACE=/workspace PYTHONUNBUFFERED=1
COPY agent/devenv_worker.py agent/prompt.md agent/prompt-norepo.md /opt/worker/
USER agent
WORKDIR /workspace
VOLUME ["/workspace"]
ENTRYPOINT ["python3", "/opt/worker/devenv_worker.py"]

FROM base AS claude
ARG CLAUDE_CODE_VERSION=2.1.330
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && npm cache clean --force
ENV WORKER_PROVIDER=claude DISABLE_AUTOUPDATER=1

FROM base AS codex
ARG CODEX_VERSION=0.171.0
RUN npm install -g "@openai/codex@${CODEX_VERSION}" && npm cache clean --force
ENV WORKER_PROVIDER=codex
