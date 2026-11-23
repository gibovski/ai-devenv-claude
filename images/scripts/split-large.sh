#!/usr/bin/env bash
# Split any file over GitHub's 2 GiB release-asset limit into numbered parts and write SHA256SUMS.
# Re-join with: cat name.part* > name   (Windows: the deploy script joins them for you).
# Usage: split-large.sh <dir>
set -euo pipefail
dir=$1
limit=$((2000 * 1024 * 1024))
part=$((1900 * 1024 * 1024))
cd "$dir"
sha256sum -- * > SHA256SUMS.full
for f in *; do
  case $f in SHA256SUMS*|*.part[0-9]*) continue ;; esac
  size=$(stat -c %s "$f")
  if [ "$size" -gt "$limit" ]; then
    split -b "$part" -d -a 2 "$f" "$f.part"
    rm -f "$f"
    echo "split $f ($size bytes)"
  fi
done
sha256sum -- *.part* 2>/dev/null > SHA256SUMS.parts || true
cat SHA256SUMS.full > SHA256SUMS
rm SHA256SUMS.full
ls -lh
