#!/usr/bin/env bash
# Developer tooling on the host: git, gh, Node.js LTS, Python + uv, build tools.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get install -y --no-install-recommends \
  git git-lfs build-essential pkg-config make cmake \
  python3 python3-venv python3-pip pipx shellcheck ripgrep fd-find tree

# GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli.gpg
chmod a+r /etc/apt/keyrings/githubcli.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list

# Node.js 22 LTS
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
  > /etc/apt/sources.list.d/nodesource.list

apt-get update
apt-get install -y gh nodejs

# uv for Python
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

git --version
gh --version
node --version
uv --version
