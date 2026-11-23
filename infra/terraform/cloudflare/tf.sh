#!/usr/bin/env bash
# Run Terraform for the Cloudflare tunnel with state in Cloudflare R2.
# Needs: CLOUDFLARE_API_TOKEN (Account: Cloudflare Tunnel Edit, Access: Apps and Policies Edit,
#        Access: Service Tokens Edit, Workers R2 Storage Edit; Zone: DNS Edit, Zone Read),
#        TF_VAR_account_id, TF_VAR_zone, TF_VAR_hostname. Optional TF_VAR_allowed_emails='["a@b.c"]'.
# Usage: tf.sh apply|plan|destroy|output [args]
set -euo pipefail
cd "$(dirname "$0")"
: "${CLOUDFLARE_API_TOKEN:?}" "${TF_VAR_account_id:?}" "${TF_VAR_hostname:?}"
api=https://api.cloudflare.com/client/v4
bucket=${TF_STATE_BUCKET:-devenv-claude-tfstate}
auth=(-H "Authorization: Bearer $CLOUDFLARE_API_TOKEN")

# R2's S3 credentials derive from the API token: key id = token id, secret = sha256(token).
token_id=$(curl -fsS "${auth[@]}" "$api/user/tokens/verify" | jq -r '.result.id // empty' || true)
if [ -z "$token_id" ]; then
  token_id=$(curl -fsS "${auth[@]}" "$api/accounts/$TF_VAR_account_id/tokens/verify" | jq -r '.result.id')
fi
export AWS_ACCESS_KEY_ID=$token_id
AWS_SECRET_ACCESS_KEY=$(printf '%s' "$CLOUDFLARE_API_TOKEN" | sha256sum | cut -d' ' -f1)
export AWS_SECRET_ACCESS_KEY

if ! curl -fsS "${auth[@]}" "$api/accounts/$TF_VAR_account_id/r2/buckets/$bucket" >/dev/null 2>&1; then
  curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -X POST \
    "$api/accounts/$TF_VAR_account_id/r2/buckets" -d "{\"name\":\"$bucket\"}" >/dev/null
fi

terraform init -input=false -reconfigure \
  -backend-config="bucket=$bucket" \
  -backend-config="key=tunnels/${TF_VAR_hostname}.tfstate" \
  -backend-config="region=auto" \
  -backend-config="endpoints={s3=\"https://$TF_VAR_account_id.r2.cloudflarestorage.com\"}" \
  -backend-config="skip_credentials_validation=true" \
  -backend-config="skip_region_validation=true" \
  -backend-config="skip_requesting_account_id=true" \
  -backend-config="skip_metadata_api_check=true" \
  -backend-config="skip_s3_checksum=true" \
  -backend-config="use_path_style=true" >/dev/null

cmd=${1:-plan}
shift || true
case $cmd in
  apply) terraform apply -input=false -auto-approve "$@" ;;
  plan) terraform plan -input=false "$@" ;;
  destroy) terraform destroy -input=false -auto-approve "$@" ;;
  output) terraform output "$@" ;;
  *) echo "unknown command $cmd" >&2; exit 2 ;;
esac
