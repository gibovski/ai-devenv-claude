#!/usr/bin/env bash
# Generalise the image: remove build credentials and per-machine state, then zero free space.
set -euxo pipefail

# Inventory for the SBOM; Packer downloads these after this script.
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > /var/tmp/packages.tsv
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -v '<none>' > /var/tmp/images.txt || true

# Remove the build-time password; devenv-firstboot sets a new one.
usermod -p '*' dev
rm -f /etc/ssh/ssh_host_*
cat > /etc/systemd/system/ssh-keygen-devenv.service <<'UNIT'
[Unit]
Description=Regenerate SSH host keys
Before=ssh.service
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key
[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A
[Install]
WantedBy=multi-user.target
UNIT
systemctl enable ssh-keygen-devenv.service

apt-get -y autoremove --purge
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/*
# The build left cloud-init's netplan bound to the build NIC's MAC address. With the seed gone, nothing
# regenerates it on Hyper-V (eth0, another MAC), so the VM came up with no address. Use DHCP on any
# Ethernet NIC instead.
cloud-init clean --logs --seed --configs network
rm -f /etc/netplan/50-cloud-init.yaml
install -m 600 /dev/stdin /etc/netplan/01-devenv-dhcp.yaml <<'NETPLAN'
network:
  version: 2
  ethernets:
    any-ethernet:
      match:
        name: "e*"
      dhcp4: true
      dhcp6: true
      dhcp-identifier: mac
      optional: true
NETPLAN
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
journalctl --rotate || true
journalctl --vacuum-time=1s || true
fstrim -av || true
sync
