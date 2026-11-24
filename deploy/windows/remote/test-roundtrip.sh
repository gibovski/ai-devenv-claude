#!/usr/bin/env bash
# CI check for backup.sh and restore.sh on a throwaway machine (needs sudo and docker; it writes to
# /var/lib/devenv and /opt/devenv, so never run it on a real VM).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
home=$(mktemp -d)
label=(--label com.docker.compose.project=devenv)
docker pull -q busybox:1.36 >/dev/null
sudo docker volume rm -f devenv_control-plane-data >/dev/null 2>&1 || true

# The "old VM": state, database, uploads, a running control plane and worker.
sudo install -d -m 0700 /var/lib/devenv
sudo install -d -o 1000 -g 1000 -m 0700 /var/lib/devenv/codex-auth
echo KEY-OLD | sudo tee /var/lib/devenv/secret.key >/dev/null
echo '{"tokens":1}' | sudo tee /var/lib/devenv/codex-auth/auth.json >/dev/null
sudo chown 1000:1000 /var/lib/devenv/codex-auth/auth.json
sudo install -d /opt/devenv/bin
echo v-old | sudo tee /opt/devenv/VERSION >/dev/null
printf '#!/bin/sh\necho ran >> %s/stack-up.log\n' "$home" | sudo tee /opt/devenv/bin/stack-up >/dev/null
sudo chmod +x /opt/devenv/bin/stack-up
sudo docker volume create devenv_control-plane-data >/dev/null
vol=$(sudo docker volume inspect -f '{{.Mountpoint}}' devenv_control-plane-data)
echo DB-OLD | sudo tee "$vol/devenv.sqlite3" >/dev/null
sudo install -d "$vol/uploads/1" && echo upload | sudo tee "$vol/uploads/1/7" >/dev/null
sudo docker run -d --name devenv-cp "${label[@]}" --label com.docker.compose.service=control-plane \
  -v devenv_control-plane-data:/data busybox:1.36 sleep 600 >/dev/null
sudo docker run -d --name devenv-wk "${label[@]}" --label com.docker.compose.service=worker-claude busybox:1.36 sleep 600 >/dev/null

HOME=$home bash "$here/backup.sh" | grep -q "BACKUP-OK .* from v-old"
[ "$(sudo docker inspect -f '{{.State.Running}}' devenv-cp)" = true ] || { echo "control plane not restarted"; exit 1; }
cp "$home/devenv-backup.tgz" "$home/kept.tgz"

# The "new VM": different key, empty database.
echo KEY-NEW | sudo tee /var/lib/devenv/secret.key >/dev/null
sudo rm -rf /var/lib/devenv/codex-auth "$vol/uploads"
echo DB-NEW | sudo tee "$vol/devenv.sqlite3" >/dev/null
echo v-new | sudo tee /opt/devenv/VERSION >/dev/null
HOME=$home bash "$here/restore.sh" | grep -q "RESTORE-OK from v-old onto v-new"

[ "$(sudo cat /var/lib/devenv/secret.key)" = KEY-OLD ]
[ "$(sudo cat "$vol/devenv.sqlite3")" = DB-OLD ]
[ "$(sudo cat "$vol/uploads/1/7")" = upload ]
[ "$(sudo stat -c %u /var/lib/devenv/codex-auth/auth.json)" = 1000 ]
[ -z "$(sudo docker ps -aq --filter label=com.docker.compose.project=devenv)" ]  # stack-up recreates them
grep -q ran "$home/stack-up.log"
[ ! -e "$home/devenv-backup.tgz" ]  # the copy on the VM is removed

# A broken file is refused before anything is touched.
echo junk > "$home/devenv-backup.tgz"
if HOME=$home bash "$here/restore.sh" 2>/dev/null; then echo "junk restored"; exit 1; fi
[ "$(sudo cat /var/lib/devenv/secret.key)" = KEY-OLD ]
echo "backup/restore round trip OK"
