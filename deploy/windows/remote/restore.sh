#!/usr/bin/env bash
# Runs on the VM (as dev, through SSH): replaces this VM's settings, credentials and queue with the ones
# in ~/devenv-backup.tgz (made by backup.sh), then starts the stack again. The SSH password of "dev" is
# not touched; the browser admin password becomes the one from the backup.
set -euo pipefail
f="$HOME/devenv-backup.tgz"
[ -f "$f" ] || { echo "ERROR: $f not found" >&2; exit 1; }
t=$(sudo mktemp -d)
trap 'sudo rm -rf "$t"; rm -f "$f"' EXIT
sudo tar -xzf "$f" -C "$t"
if ! sudo test -f "$t/state/secret.key" || ! sudo test -f "$t/data/devenv.sqlite3"; then
  echo "ERROR: this is not a devenv backup (no state/secret.key or data/devenv.sqlite3)" >&2
  exit 1
fi
# On a brand-new VM the first boot may still be starting the stack: let it finish first.
for _ in $(seq 180); do
  [ "$(systemctl is-active devenv-stack.service 2>/dev/null || true)" = activating ] || break
  sleep 5
done
# Stop everything of the stack; stack-up recreates it from the restored settings.
mapfile -t ids < <(sudo docker ps -aq --filter label=com.docker.compose.project=devenv)
if [ "${#ids[@]}" -gt 0 ]; then sudo docker rm -f "${ids[@]}" >/dev/null; fi
if ! sudo docker volume inspect devenv_control-plane-data >/dev/null 2>&1; then
  sudo docker volume create --label com.docker.compose.project=devenv --label com.docker.compose.volume=control-plane-data \
    devenv_control-plane-data >/dev/null
fi
vol=$(sudo docker volume inspect -f '{{.Mountpoint}}' devenv_control-plane-data)
sudo find /var/lib/devenv -mindepth 1 -delete
sudo cp -a "$t/state/." /var/lib/devenv/
sudo chmod 0700 /var/lib/devenv
sudo find "$vol" -mindepth 1 -delete
sudo cp -a "$t/data/." "$vol/"
sudo /opt/devenv/bin/stack-up >/dev/null
echo "RESTORE-OK from $(sudo cat "$t/VERSION" 2>/dev/null || echo unknown) onto $(cat /opt/devenv/VERSION 2>/dev/null || echo unknown)"
