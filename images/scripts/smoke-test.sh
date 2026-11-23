#!/usr/bin/env bash
# shellcheck disable=SC2054  # commas are part of QEMU -drive options
# Boot a built image under QEMU, wait for cloud-init and the stack, then run health checks.
# Usage: smoke-test.sh <image.qcow2> <arch>
set -euo pipefail
img=$1 arch=$2
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'kill "${qpid:-0}" 2>/dev/null || true; rm -rf "$work"' EXIT

ssh-keygen -q -t ed25519 -N "" -f "$work/key"
"$here/../cloud-init/make-seed.sh" -N -o "$work/seed.iso" -k "$work/key.pub" >/dev/null
qemu-img create -q -f qcow2 -F qcow2 -b "$(realpath "$img")" "$work/disk.qcow2"

accel=tcg; [ -w /dev/kvm ] && accel=kvm
if [ "$arch" = arm64 ]; then
  cp /usr/share/AAVMF/AAVMF_VARS.fd "$work/vars.fd"
  qemu=(qemu-system-aarch64 -machine virt -cpu "$([ $accel = kvm ] && echo host || echo max)"
        -drive if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd
        -drive if=pflash,format=raw,file="$work/vars.fd")
  timeout=5400
else
  cp /usr/share/OVMF/OVMF_VARS_4M.fd "$work/vars.fd"
  qemu=(qemu-system-x86_64 -machine q35 -cpu "$([ $accel = kvm ] && echo host || echo max)"
        -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
        -drive if=pflash,format=raw,file="$work/vars.fd")
  timeout=900
fi
[ $accel = tcg ] && timeout=$((timeout * 3))

"${qemu[@]}" -accel $accel -smp 4 -m 6144 -display none -serial file:"$work/console.log" \
  -drive file="$work/disk.qcow2",if=virtio -drive file="$work/seed.iso",media=cdrom,if=virtio \
  -nic user,model=virtio-net-pci,mac=52:54:00:de:5e:01,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:80 &
qpid=$!

ssh_() { ssh -q -i "$work/key" -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 dev@127.0.0.1 "$@"; }

echo "waiting for SSH (accel=$accel, timeout=${timeout}s)"
end=$((SECONDS + timeout))
until ssh_ true 2>/dev/null; do
  [ $SECONDS -gt $end ] && { echo "SSH timeout"; tail -50 "$work/console.log"; exit 1; }
  kill -0 $qpid || { echo "qemu exited"; tail -50 "$work/console.log"; exit 1; }
  sleep 10
done

echo "== cloud-init"
ssh_ 'cloud-init status --wait --long' || true
ssh_ 'cloud-init status' | grep -qE 'done|disabled'

echo "== services"
for unit in docker devenv-firstboot devenv-stack; do
  ssh_ "systemctl is-active $unit" || { ssh_ "sudo journalctl -u $unit --no-pager | tail -50"; exit 1; }
done
ssh_ 'docker --version && docker compose version && git --version && gh --version | head -1 && node --version && uv --version'
ssh_ 'test -s /etc/issue.net && cat /etc/issue.net'

if ssh_ 'test -f /opt/devenv/compose.yaml'; then
  echo "== stack health"
  end=$((SECONDS + timeout))
  until curl -fsS http://127.0.0.1:8080/api/health; do
    [ $SECONDS -gt $end ] && { ssh_ 'docker ps -a; cd /opt/devenv && sudo docker compose -p devenv logs --tail 80'; exit 1; }
    sleep 10
  done
  echo
  curl -fsS -o /dev/null http://127.0.0.1:8080/
fi
echo "SMOKE TEST PASSED"

# Optional end-to-end stage: E2E_HOOK is a script that gets the UI URL and the admin password.
if [ -n "${E2E_HOOK:-}" ]; then
  pw=$(ssh_ 'sudo cat /var/lib/devenv/initial-admin-password')
  DEVENV_URL=http://127.0.0.1:8080 DEVENV_ADMIN_PASSWORD="$pw" "$E2E_HOOK" || {
    ssh_ 'cd /opt/devenv && sudo docker compose -p devenv ps; sudo docker compose -p devenv logs --tail 120'; exit 1; }
fi
