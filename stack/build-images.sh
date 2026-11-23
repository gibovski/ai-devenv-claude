#!/usr/bin/env bash
# Build the stack images for one platform and save them as tarballs for baking into the VM.
# Usage: build-images.sh <platform e.g. linux/amd64> <outdir> [tag]
set -euo pipefail
platform=$1 out=$2 tag=${3:-latest}
root=$(cd "$(dirname "$0")/.." && pwd)
registry=ghcr.io/gibovski/ai-devenv-claude
mkdir -p "$out"
# name:context pairs; workers are added as they exist.
images=(control-plane:services/control-plane web:services/web)
for extra in worker-base:workers/base worker-claude:workers/claude worker-codex:workers/codex; do
  [ -f "$root/${extra#*:}/Dockerfile" ] && images+=("$extra")
done
for item in "${images[@]}"; do
  name=${item%%:*} ctx=${item#*:}
  echo "== $name ($platform)"
  docker buildx build --builder default --platform "$platform" --load \
    --build-arg "REGISTRY=$registry" --build-arg "TAG=latest" \
    -t "$registry/$name:latest" -t "$registry/$name:$tag" "$root/$ctx"
done
refs=()
for item in "${images[@]}"; do refs+=("$registry/${item%%:*}:latest" "$registry/${item%%:*}:$tag"); done
docker save -o "$out/stack-images.tar" "${refs[@]}"
ls -lh "$out"
