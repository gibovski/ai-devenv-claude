#!/usr/bin/env bash
# Docker Engine and the Compose plugin from Docker's apt repository.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

usermod -aG docker dev
cat > /etc/docker/daemon.json <<'CONF'
{
  "log-driver": "local",
  "log-opts": { "max-size": "20m", "max-file": "3" },
  "features": { "buildkit": true }
}
CONF
systemctl enable docker containerd
docker --version
docker compose version
