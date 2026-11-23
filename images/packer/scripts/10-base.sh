#!/usr/bin/env bash
# Full upgrade and base packages.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y -o Dpkg::Options::=--force-confnew full-upgrade
# Hyper-V tools (KVP daemon) only exist for amd64; Hyper-V on Windows runs amd64 guests.
hyperv=()
[ "$(dpkg --print-architecture)" = amd64 ] && hyperv=(linux-cloud-tools-virtual linux-tools-virtual)
apt-get install -y --no-install-recommends \
  ca-certificates curl wget gnupg lsb-release jq unzip zip xz-utils zstd \
  avahi-daemon libnss-mdns openssh-server sudo vim less htop tmux \
  "${hyperv[@]}" qemu-guest-agent \
  open-vm-tools cloud-guest-utils cloud-initramfs-growroot

# Hyper-V integration services (KVP, VSS) and guest agents for other hypervisors.
systemctl enable qemu-guest-agent || true
systemctl enable hv-kvp-daemon.service 2>/dev/null || true
systemctl enable hv-fcopy-daemon.service 2>/dev/null || true  # Copy-VMFile
systemctl enable hv-vss-daemon.service 2>/dev/null || true

# Hostname devenv, reachable as devenv.local via mDNS.
hostnamectl set-hostname devenv || echo devenv > /etc/hostname
sed -i 's/^#\?publish-workstation=.*/publish-workstation=yes/' /etc/avahi/avahi-daemon.conf
systemctl enable avahi-daemon

# Headless: allow password SSH (password is generated on first boot) and keys.
cat > /etc/ssh/sshd_config.d/10-devenv.conf <<'CONF'
PasswordAuthentication yes
KbdInteractiveAuthentication no
PrintMotd yes
Banner /etc/issue.net
CONF

# Do not wait for a metadata service that will never answer on a laptop.
cat > /etc/cloud/cloud.cfg.d/90-devenv-datasource.cfg <<'CONF'
datasource_list: [NoCloud, ConfigDrive, None]
CONF
