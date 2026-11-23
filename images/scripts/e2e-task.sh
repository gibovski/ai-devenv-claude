#!/usr/bin/env bash
# End-to-end check run against a booted VM (see smoke-test.sh E2E_HOOK): log in, configure
# credentials and one Claude agent, apply, queue a task against a sandbox repo and wait until the
# definition of done says "done" (PR merged into main).
# Env: DEVENV_URL, DEVENV_ADMIN_PASSWORD, E2E_REPO (owner/name), E2E_GITHUB_TOKEN, E2E_ANTHROPIC_API_KEY,
#      optional E2E_MODEL (default claude-haiku-5-5), E2E_TIMEOUT seconds (default 2400).
set -euo pipefail
: "${DEVENV_URL:?}" "${DEVENV_ADMIN_PASSWORD:?}" "${E2E_REPO:?}" "${E2E_GITHUB_TOKEN:?}" "${E2E_ANTHROPIC_API_KEY:?}"
model=${E2E_MODEL:-claude-haiku-5-5}
timeout=${E2E_TIMEOUT:-2400}
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
api() { local m=$1 p=$2; shift 2; curl -fsS -b "$jar" -c "$jar" -X "$m" -H 'Content-Type: application/json' "$DEVENV_URL/api$p" "$@"; }

echo "== login"
api POST /auth/login -d "$(jq -n --arg p "$DEVENV_ADMIN_PASSWORD" '{username:"admin",password:$p}')" >/dev/null
newpw=$(openssl rand -base64 18)
api POST /auth/password -d "$(jq -n --arg c "$DEVENV_ADMIN_PASSWORD" --arg n "$newpw" '{current:$c,new:$n}')" >/dev/null

echo "== settings"
owner=${E2E_REPO%%/*} name=${E2E_REPO#*/}
api PUT /secrets -d "$(jq -n --arg g "$E2E_GITHUB_TOKEN" --arg a "$E2E_ANTHROPIC_API_KEY" \
  '{values:{github_token:$g,anthropic_api_key:$a}}')" >/dev/null
api GET /settings | jq --arg o "$owner" --arg n "$name" --arg m "$model" \
  '.settings | .github.owner=$o | .github.default_repo=$n | .github.auto_merge=true
   | .agents.claude.count=1 | .agents.claude.model=$m | .agents.codex.count=0' > "$jar.settings"
api PUT /settings --data-binary @"$jar.settings" >/dev/null
rm -f "$jar.settings"
api POST /settings/check/github | jq -c .
api POST /settings/check/anthropic | jq -c .

echo "== apply"
run=$(api POST /apply | jq -r .run_id)
for _ in $(seq 1 90); do
  st=$(api GET "/apply/runs/$run" | jq -r .status)
  [ "$st" = running ] || break
  sleep 5
done
api GET "/apply/runs/$run" | jq -r '.status, (.log // "")' | tail -40
[ "$st" = succeeded ] || { echo "apply ended with $st"; exit 1; }

echo "== queue task"
stamp=$(date -u +%Y%m%d-%H%M%S)
task=$(api POST /tasks -d "$(jq -n --arg r "$E2E_REPO" --arg s "$stamp" '{
  title: ("E2E: add e2e/" + $s + ".md"),
  description: ("Create the file e2e/" + $s + ".md containing one line: \\"hello from the devenv e2e test\\". Open a pull request for it."),
  repo: $r, provider: "claude", max_attempts: 2}')" | jq -r .id)
echo "task $task"

end=$((SECONDS + timeout)); last=""
while [ $SECONDS -lt $end ]; do
  st=$(api GET "/tasks/$task" | jq -r .status)
  [ "$st" != "$last" ] && { echo "$(date -u +%T) $st"; last=$st; }
  case $st in
    done) api GET "/tasks/$task" | jq '{id,status,pr_url}'; echo "E2E PASSED"; exit 0 ;;
    failed|needs_human|cancelled) api GET "/tasks/$task/events" | jq -r '.[] | "\(.kind): \(.message)"' | tail -40; exit 1 ;;
  esac
  sleep 20
done
echo "timed out in status $st"; api GET "/tasks/$task/events" | jq -r '.[] | "\(.kind): \(.message)"' | tail -40; exit 1
