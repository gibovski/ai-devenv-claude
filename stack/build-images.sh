#!/usr/bin/env bash
# Build the stack images for one platform and save them as tarballs for baking into the VM.
# Usage: build-images.sh <platform e.g. linux/amd64> <outdir> [tag]
set -euo pipefail
platform=$1 out=$2 tag=${3:-latest}
root=$(cd "$(dirname "$0")/.." && pwd)
registry=ghcr.io/gibovski/ai-devenv-claude
mkdir -p "$out"
# name:context:target (target may be empty)
images=(control-plane:services/control-plane: web:services/web: worker-claude:workers:claude worker-codex:workers:codex)
for item in "${images[@]}"; do
  IFS=: read -r name ctx target <<<"$item"
  echo "== $name ($platform)"
  docker buildx build --builder default --platform "$platform" --load ${target:+--target "$target"} \
    -t "$registry/$name:latest" -t "$registry/$name:$tag" "$root/$ctx"
done
refs=()
for item in "${images[@]}"; do refs+=("$registry/${item%%:*}:latest" "$registry/${item%%:*}:$tag"); done
docker save -o "$out/stack-images.tar" "${refs[@]}"
ls -lh "$out"
