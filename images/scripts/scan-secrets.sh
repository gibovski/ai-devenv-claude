#!/usr/bin/env bash
# Fail if a built image contains credentials or per-VM state. Images are meant to be shared, so every
# credential must be entered later in the settings UI and every key must be generated on first boot.
# Usage: scan-secrets.sh <image.qcow2>
# Env: SCAN_VALUES  newline-separated exact values that must not appear anywhere (e.g. CI secrets)
set -euo pipefail
img=$(realpath "$1")
mnt=$(mktemp -d)
pat=$(mktemp)
chmod 600 "$pat"
# shellcheck disable=SC2317,SC2329  # invoked by the EXIT trap
cleanup() { sudo umount "$mnt" 2>/dev/null || true; sudo qemu-nbd -d /dev/nbd0 >/dev/null 2>&1 || true; rm -rf "$mnt" "$pat"; }
trap cleanup EXIT

sudo modprobe nbd max_part=8
sudo qemu-nbd -r -c /dev/nbd0 "$img"
for _ in $(seq 1 20); do [ -e /dev/nbd0p1 ] && break; sleep 0.5; done
sudo udevadm settle 2>/dev/null || true
# Find the root filesystem by probing the partitions directly (no blkid cache, no udev data),
# then mount it, retrying while the nbd device finishes setting up.
root=""
for _ in $(seq 1 10); do
  for p in /dev/nbd0p*; do
    if [ "$(sudo blkid -p -o value -s LABEL "$p" 2>/dev/null)" = cloudimg-rootfs ]; then root=$p; break; fi
  done
  [ -n "$root" ] && break
  sleep 2
done
[ -n "$root" ] || { echo "no root filesystem found"; lsblk /dev/nbd0; sudo blkid -p /dev/nbd0p* || true; exit 1; }
for i in $(seq 1 10); do
  if sudo mount -o ro,noload -t ext4 "$root" "$mnt"; then break; fi
  [ "$i" = 10 ] && { sudo dmesg | tail -20; exit 1; }
  sleep 2
done
sudo test -e "$mnt/etc/os-release" || { echo "mounted $root but it has no /etc/os-release"; sudo ls "$mnt"; exit 1; }
echo "scanning $root"
fail=0

echo "== per-VM state that must be created on first boot"
# /var/lib/devenv holds keys, the database, stored credentials and the one-time password: all per VM.
if state=$(sudo find "$mnt/var/lib/devenv" -type f 2>/dev/null) && [ -n "$state" ]; then
  echo "::error::image ships files in /var/lib/devenv (must be created on first boot):"
  printf '  %s\n' "${state//$mnt/}"; fail=1
fi
if sudo sh -c "ls '$mnt'/etc/ssh/ssh_host_*_key 2>/dev/null" | grep -q .; then
  echo "::error::image contains SSH host keys"; fail=1
fi
for home in "$mnt"/root "$mnt"/home/*; do
  for f in .git-credentials .config/gh/hosts.yml .claude/.credentials.json .codex/auth.json .docker/config.json; do
    if sudo test -s "$home/$f"; then echo "::error::image contains ${home#"$mnt"}/$f"; fail=1; fi
  done
done

echo "== known secret values"
printf '%s\n' "${SCAN_VALUES:-}" | awk 'length($0) >= 8' > "$pat"
if [ -s "$pat" ]; then
  # -F exact strings, -a binary files too; print only file names, never the match.
  if hits=$(sudo grep -rlaF -f "$pat" "$mnt" --exclude-dir=proc --exclude-dir=sys 2>/dev/null); then
    echo "::error::a CI secret value was found in the image in:"; printf '  %s\n' "${hits//$mnt/}"; fail=1
  fi
fi

echo "== credential-shaped strings in text files"
re='sk-ant-(api|oat|admin)[0-9]{2}-[A-Za-z0-9_-]{40,}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|sk-(proj-)?[A-Za-z0-9_-]{40,}T3BlbkFJ'
if hits=$(sudo grep -rlIE "$re" "$mnt" --exclude-dir=proc --exclude-dir=sys --exclude-dir=usr --exclude-dir=snap 2>/dev/null); then
  echo "::error::credential-shaped strings found in:"; printf '  %s\n' "${hits//$mnt/}"; fail=1
fi

[ $fail -eq 0 ] && echo "NO CREDENTIALS IN IMAGE"
exit $fail
