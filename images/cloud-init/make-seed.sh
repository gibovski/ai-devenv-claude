#!/usr/bin/env bash
# Build a cloud-init NoCloud seed ISO (label "cidata") to customise a VM at first boot.
# Usage: make-seed.sh -o seed.iso [-n hostname] [-k ~/.ssh/id_ed25519.pub] [-u dev] [-p password] [-N]
# -N leaves networking to the image (as on Hyper-V, where there is no seed); CI uses it.
# The image works without a seed; use one to add SSH keys or change the hostname.
set -euo pipefail
out=seed.iso host=devenv user=dev key="" pass="" nonet=""
while getopts "o:n:k:u:p:N" opt; do
  case $opt in
    o) out=$OPTARG ;; n) host=$OPTARG ;; k) key=$OPTARG ;; u) user=$OPTARG ;; p) pass=$OPTARG ;; N) nonet=1 ;;
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

files=("$tmp/user-data" "$tmp/meta-data")
if [ -n "$nonet" ]; then
  printf 'network:\n  config: disabled\n' > "$tmp/network-config"
  files+=("$tmp/network-config")
fi
if command -v genisoimage >/dev/null; then
  genisoimage -quiet -output "$out" -volid cidata -joliet -rock "${files[@]}"
else
  xorriso -as mkisofs -quiet -o "$out" -V cidata -J -r "${files[@]}"
fi
echo "wrote $out"
