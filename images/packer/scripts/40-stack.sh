#!/usr/bin/env bash
# Install the Docker Compose stack, the first-boot service and the stack service.
set -euxo pipefail

install -d -m 0755 /opt/devenv
install -d -m 1777 /tmp/stack-images  # the next file provisioner uploads here as the build user
cp -r /tmp/stack/. /opt/devenv/
install -d -m 0755 /opt/devenv/terraform /opt/devenv/mcp
cp -r /tmp/terraform-cloudflare /opt/devenv/terraform/cloudflare
cp -r /tmp/mcp/. /opt/devenv/mcp/
install -d -m 0700 /var/lib/devenv
install -d -m 0700 -o 1000 -g 1000 /var/lib/devenv/codex-auth  # shared ChatGPT sign-in for Codex agents (empty)
echo "${DEVENV_VERSION:-dev}" > /opt/devenv/VERSION
echo "${DEVENV_ARCH:-unknown}" > /opt/devenv/ARCH

install -m 0755 /tmp/files/devenv-firstboot /usr/local/sbin/devenv-firstboot
install -m 0755 /tmp/files/devenv-issue /usr/local/sbin/devenv-issue
install -m 0644 /tmp/files/devenv-firstboot.service /etc/systemd/system/
install -m 0644 /tmp/files/devenv-stack.service /etc/systemd/system/
install -m 0644 /tmp/files/devenv-issue.service /tmp/files/devenv-issue.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable devenv-firstboot.service devenv-stack.service devenv-issue.service devenv-issue.timer
