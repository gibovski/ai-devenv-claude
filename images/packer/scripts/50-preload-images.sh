#!/usr/bin/env bash
# Load pre-built stack images so the first boot needs no registry access.
set -euxo pipefail
shopt -s nullglob
for tar in /tmp/stack-images/*.tar; do
  docker load -i "$tar"
done
rm -rf /tmp/stack-images
docker image ls
