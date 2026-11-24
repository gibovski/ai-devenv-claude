#!/usr/bin/env bash
# Runs on the VM (as dev, through SSH): packs the settings, encrypted credentials, encryption key, queue
# and uploads into ~/devenv-backup.tgz. Works on every image version: it only needs sudo, docker and tar.
#   state/  = /var/lib/devenv (secret.key, compose override, agent config, Codex sign-in, ...)
#   data/   = the control-plane-data volume (devenv.sqlite3: settings, secrets, tasks, tokens; uploads)
set -euo pipefail
out="$HOME/devenv-backup.tgz"
vol=$(sudo docker volume inspect -f '{{.Mountpoint}}' devenv_control-plane-data 2>/dev/null || true)
if [ -z "$vol" ] || ! sudo test -f "$vol/devenv.sqlite3"; then
  echo "ERROR: no control-plane database on this VM (docker volume devenv_control-plane-data)" >&2
  exit 1
fi
# Stop the control plane for a moment so the database is copied in a consistent state.
mapfile -t cp_ids < <(sudo docker ps -q --filter label=com.docker.compose.project=devenv --filter label=com.docker.compose.service=control-plane)
t=$(sudo mktemp -d)
cleanup() {
  if [ "${#cp_ids[@]}" -gt 0 ]; then sudo docker start "${cp_ids[@]}" >/dev/null || true; fi
  sudo rm -rf "$t"
}
trap cleanup EXIT
if [ "${#cp_ids[@]}" -gt 0 ]; then sudo docker stop "${cp_ids[@]}" >/dev/null; fi
sudo mkdir "$t/b"
sudo cp -a /var/lib/devenv "$t/b/state"
sudo cp -a "$vol" "$t/b/data"
{ cat /opt/devenv/VERSION 2>/dev/null || echo unknown; } | sudo tee "$t/b/VERSION" >/dev/null
rm -f "$out"
sudo tar -C "$t/b" -czf "$out" .
sudo chown "$(id -u):$(id -g)" "$out"
chmod 600 "$out"
echo "BACKUP-OK $(du -h "$out" | cut -f1) from $(sudo cat "$t/b/VERSION")"
