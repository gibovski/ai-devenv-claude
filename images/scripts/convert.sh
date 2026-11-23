#!/usr/bin/env bash
# Convert the Packer qcow2 into the published formats.
# Usage: convert.sh <input.qcow2> <outdir> <basename> <arch>
# Produces: <basename>.qcow2, <basename>.vhdx.zip (Hyper-V), <basename>.ova, <basename>.raw.zst
set -euo pipefail
in=$1 out=$2 base=$3 arch=$4
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$out"

echo "== qcow2 (compressed)"
qemu-img convert -p -c -O qcow2 "$in" "$out/$base.qcow2"

echo "== vhdx (Hyper-V Gen2), zipped"
qemu-img convert -p -O vhdx -o subformat=dynamic "$in" "$out/$base.vhdx"
(cd "$out" && zip -1 -m "$base.vhdx.zip" "$base.vhdx")

echo "== ova (VirtualBox / VMware)"
tmp=$(mktemp -d)
qemu-img convert -p -O vmdk -o subformat=streamOptimized "$in" "$tmp/$base-disk1.vmdk"
disk_bytes=$(qemu-img info --output=json "$in" | jq '.["virtual-size"]')
file_bytes=$(stat -c %s "$tmp/$base-disk1.vmdk")
BASE=$base ARCH=$arch DISK_BYTES=$disk_bytes FILE_BYTES=$file_bytes envsubst < "$here/ovf.template.xml" > "$tmp/$base.ovf"
(cd "$tmp" && sha256sum "$base.ovf" "$base-disk1.vmdk" | awk '{print "SHA256("$2")= "$1}' > "$base.mf")
tar -C "$tmp" -cf "$out/$base.ova" "$base.ovf" "$base-disk1.vmdk" "$base.mf"
rm -rf "$tmp"

echo "== raw, zstd-compressed"
qemu-img convert -p -O raw "$in" "$out/$base.raw"
zstd -T0 -10 --rm -q "$out/$base.raw" -o "$out/$base.raw.zst"

ls -lh "$out"
