#!/usr/bin/env bash
# Build a cloud-init NoCloud seed ISO (label "cidata") to customise a VM at first boot.
# Usage: make-seed.sh -o seed.iso [-n hostname] [-k ~/.ssh/id_ed25519.pub] [-u dev] [-p password]
# The image works without a seed; use one to add SSH keys or change the hostname.
set -euo pipefail
out=seed.iso host=devenv user=dev key="" pass=""
while getopts "o:n:k:u:p:" opt; do
  case $opt in
    o) out=$OPTARG ;; n) host=$OPTARG ;; k) key=$OPTARG ;; u) user=$OPTARG ;; p) pass=$OPTARG ;;
    *) sed -n '2,4p' "$0"; exit 2 ;;
  esac
done
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/meta-data" <<META
instance-id: devenv-$(date +%s)
local-hostname: $host
META

{
  echo "#cloud-config"
  echo "hostname: $host"
  echo "users:"
  echo "  - default"
  echo "  - name: $user"
  echo "    groups: [sudo, adm, docker]"
  echo "    shell: /bin/bash"
  echo "    sudo: \"ALL=(ALL) NOPASSWD:ALL\""
  if [ -n "$key" ]; then
    echo "    ssh_authorized_keys:"
    echo "      - $(cat "$key")"
  fi
  if [ -n "$pass" ]; then
    echo "    lock_passwd: false"
    echo "    plain_text_passwd: $pass"
  fi
} > "$tmp/user-data"

if command -v cloud-localds >/dev/null; then
  cloud-localds "$out" "$tmp/user-data" "$tmp/meta-data"
elif command -v genisoimage >/dev/null; then
  genisoimage -quiet -output "$out" -volid cidata -joliet -rock "$tmp/user-data" "$tmp/meta-data"
else
  xorriso -as mkisofs -quiet -o "$out" -V cidata -J -r "$tmp/user-data" "$tmp/meta-data"
fi
echo "wrote $out"
